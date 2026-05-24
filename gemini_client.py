import os
import logging
from datetime import datetime, timezone
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# ── Base system prompt ────────────────────────────────────────────────
# Keep this lean — dynamic context (pantry, profile, nutrition) is injected
# per-request in chat() so it stays accurate and doesn't bloat the base prompt.

SYSTEM_PROMPT = """You are a warm, friendly cooking and grocery assistant for elderly users.

PERSONA:
- Use simple, clear everyday language. No complex cooking terms.
- Keep sentences short and easy to understand.
- Always be warm, patient, and encouraging.

---

FORMAT GUIDE — pick the ONE format that fits the request:

For RECIPE requests:

[Recipe Name]

Time: [X] minutes | Serves: [X] people

WHAT YOU NEED:
1. [amount] [ingredient]
2. [amount] [ingredient]
Note: Mark any ingredient not in the pantry with "(need to buy)".

HOW TO MAKE IT:
1. [Simple step]
2. [Simple step]

Tip: [One helpful tip]

EAT BY: [e.g. "Today" or "Tomorrow" or "Within 2 days — keep in fridge"]

---

For GROCERY LIST requests:

SHOPPING LIST

1. [Item]
2. [Item]

Total items: [number]

---

For COOKING HELP (user is actively cooking):
- Give simple step-by-step guidance.
- Include safety reminders (turn off stove, do not leave unattended).
- End with: EAT BY: [timeframe]

---

For FOOD EXPIRY questions:
EAT BY: [specific date or timeframe]
Why: [one simple sentence]

---

For GENERAL QUESTIONS or CONVERSATION:
Answer in 2 to 4 short, simple sentences. Be warm and friendly.

---

FOOD SAFETY (always follow):
- Cooked pasta, rice, eggs: same day or within 1 day refrigerated
- Cooked soup or stew: within 2 days refrigerated
- Cooked chicken or meat: within 2 days refrigerated
- Baked goods: 2 to 3 days at room temperature
- General leftovers: within 2 to 3 days refrigerated
Never be vague about food safety. Always give a clear timeframe.

---

NUTRITION TRACKING:
Only when the user mentions eating or finishing a meal (e.g. "I ate pasta", "I just had soup") — append this hidden line at the very end of your response, after everything else:
DATA: {"calories": [your estimate], "protein": [your estimate in grams], "used_items": ["Item1", "Item2"]}
Do NOT include this line for recipe suggestions, grocery lists, food safety questions, or general chat.
"""


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


class GeminiClient:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
        self.client = genai.Client(api_key=api_key)

    def _build_system(self, context: dict) -> str:
        system = SYSTEM_PROMPT
        profile = context.get("profile") or {}

        # ── 1. Elder profile (name/age/weight for tone) ───────────────
        profile_lines = []
        if profile.get("name"):   profile_lines.append(f"Name: {profile['name']}")
        if profile.get("age"):    profile_lines.append(f"Age: {profile['age']}")
        if profile.get("weight"): profile_lines.append(f"Weight: {profile['weight']} kg")
        if profile.get("goals_concerns"):
            profile_lines.append(f"Caregiver notes: {profile['goals_concerns']}")
        if profile_lines:
            system += "\n\nELDER PROFILE:\n" + "\n".join(profile_lines)

        # ── 2. Cuisine cohesion ───────────────────────────────────────
        cuisine = (profile.get("cuisine") or "").strip()
        if cuisine:
            system += (
                f"\n\nCUISINE STYLE: This user enjoys {cuisine} food. "
                f"All recipe suggestions should feel cohesive with {cuisine} cuisine — "
                f"use its typical flavors, spices, and cooking techniques. "
                f"Even when adapting pantry ingredients creatively, stay true to this culinary style."
            )

        # ── 3. Dietary hard constraints ───────────────────────────────
        allergies    = (profile.get("allergies")    or "").strip()
        restrictions = (profile.get("restrictions") or "").strip()
        if allergies or restrictions:
            system += "\n\nDIETARY CONSTRAINTS:"
            if allergies:
                system += (
                    f"\n- ALLERGIES: {allergies}. "
                    f"Never include these ingredients in any suggestion, even as optional."
                )
            if restrictions:
                system += (
                    f"\n- RESTRICTIONS: {restrictions}. "
                    f"Respect these in every recipe and grocery suggestion."
                )

        # ── 4. Pantry — strong preference, not just a hint ───────────
        raw_pantry = context.get("pantry") or []
        pantry_items = [
            (i["text"] if isinstance(i, dict) else str(i))
            for i in raw_pantry
        ]
        if pantry_items:
            system += (
                f"\n\nPANTRY (what the user already has at home): {', '.join(pantry_items)}.\n"
                f"RECIPE RULE: When suggesting what to cook, strongly prefer recipes "
                f"that can be made using ONLY these pantry items. "
                f"If an important ingredient is not in the pantry, label it clearly with '(need to buy)' "
                f"and keep such extras to a minimum — ideally one or two at most. "
                f"Never suggest a recipe that requires mostly items not in the pantry "
                f"without explaining what the user needs to buy."
            )
        else:
            system += (
                "\n\nPANTRY: The user's pantry is currently empty. "
                "Ask what ingredients they have before suggesting recipes, "
                "or suggest very simple, common-ingredient meals."
            )

        # ── 5. Today's nutrition — light guidance, not strict ─────────
        nutrition_logs = context.get("nutrition_logs") or []
        today = _today_str()
        today_logs = [
            l for l in nutrition_logs
            if (l.get("timestamp") or "").startswith(today)
        ]
        if today_logs:
            total_cals = sum((l.get("cals") or 0) for l in today_logs)
            total_prot = sum((l.get("prot") or 0) for l in today_logs)
            system += (
                f"\n\nTODAY'S NUTRITION SO FAR: ~{total_cals} calories, ~{total_prot}g protein. "
                f"Use this as light guidance — don't be overly strict. "
                f"If they've eaten a lot already, lean toward lighter or smaller-portion suggestions. "
                f"If they've eaten very little, suggest something more filling."
            )

        # ── 6. Active cooking context ─────────────────────────────────
        if (context.get("mode") or "") == "cooking":
            dish = context.get("dish", "food")
            mins = int(context.get("timer_remaining", 0)) // 60
            system += (
                f"\n\nCURRENT CONTEXT: The user is actively cooking {dish}. "
                f"About {mins} minutes remain on the timer. "
                f"Focus on step-by-step cooking help and food safety for {dish}."
            )

        return system

    def chat(self, history: list, message: str, context: dict = None) -> str:
        system = self._build_system(context or {})

        gemini_history = [
            types.Content(role=msg["role"], parts=[types.Part(text=msg["content"])])
            for msg in history
        ]

        response = self.client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=gemini_history + [
                types.Content(role="user", parts=[types.Part(text=message)])
            ],
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.4,
                max_output_tokens=2048,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return response.text

    def get_expiry(self, dish: str) -> tuple:
        info = self.get_cooked_info(dish)
        return info["eat_by"] or "Within 1-2 days", info["reason"] or "Store in fridge and eat soon."

    def get_cooked_info(self, dish: str) -> dict:
        today = datetime.now().strftime("%A, %B %d, %Y")
        prompt = (
            f"The user just finished cooking {dish}. Today is {today}.\n"
            f"Reply with exactly four lines:\n"
            f"EAT BY: [a specific day name and date, e.g. 'Wednesday, May 28, 2026' — never vague]\n"
            f"WHY: [one simple sentence explaining the food safety rule]\n"
            f"CALORIES: [estimated calories for one serving, number only]\n"
            f"PROTEIN: [estimated protein grams for one serving, number only]"
        )
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                    max_output_tokens=100,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            text = (response.text or "").strip()
            result = {"eat_by": "", "reason": "", "calories": 0, "protein": 0}
            for line in text.split("\n"):
                line = line.strip()
                ul = line.upper()
                if ul.startswith("EAT BY:"):
                    result["eat_by"] = line[7:].strip()
                elif ul.startswith("WHY:"):
                    result["reason"] = line[4:].strip()
                elif ul.startswith("CALORIES:"):
                    try: result["calories"] = int(line[9:].strip().split()[0].replace(",", ""))
                    except: pass
                elif ul.startswith("PROTEIN:"):
                    try: result["protein"] = int(line[8:].strip().split()[0].replace(",", ""))
                    except: pass
            return result
        except Exception as e:
            logger.error(f"get_cooked_info error: {e}")
            return {"eat_by": "Within 1-2 days", "reason": "Store in fridge and eat soon.", "calories": 0, "protein": 0}

    def get_insights(self, items: list, profile: dict = None) -> dict:
        if not items:
            return {"meal_plan": "", "suggestions": []}

        cuisine = (profile or {}).get("cuisine", "")
        cuisine_note = f" Keep the meal plan cohesive with {cuisine} cuisine." if cuisine else ""

        prompt = (
            f"Groceries and pantry available: {', '.join(items)}.\n"
            f"1. Write a simple 3-day meal plan using mostly these items.{cuisine_note}\n"
            f"2. List 2 to 3 items that might be missing for a healthy, balanced diet.\n"
            f"Use simple language for an elderly person."
        )
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.4,
                    max_output_tokens=400,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            text = (response.text or "").strip()
            parts = [p.strip() for p in text.split("\n\n") if p.strip()]
            return {
                "meal_plan": parts[0] if parts else text,
                "suggestions": parts[1:] if len(parts) > 1 else []
            }
        except Exception as e:
            logger.error(f"get_insights error: {e}")
            return {"meal_plan": "", "suggestions": []}
