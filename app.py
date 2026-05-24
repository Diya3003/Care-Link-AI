import json, os, uuid, threading, logging
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from gemini_client import GeminiClient
    gemini = GeminiClient()
    logger.info("Gemini ready.")
except Exception as e:
    gemini = None
    logger.warning(f"Gemini unavailable: {e}")

app = Flask(__name__)
CORS(app)
STATE_FILE = "state.json"

# ── State ─────────────────────────────────────────────────────

def load():
    if not os.path.exists(STATE_FILE):
        save(default_state())
    with open(STATE_FILE) as f:
        state = json.load(f)
    state.setdefault("grocery_list",     [])
    state.setdefault("timer",            {"active": False, "dish": "", "start_time": None, "duration_minutes": 0, "dismissed": False})
    state.setdefault("grocery_meta",     {"last_updated": None, "reminder_frequency_days": 3})
    state.setdefault("family_notes",     "")
    state.setdefault("elder_activity",   {"last_opened": None, "last_timer_used": None})
    state.setdefault("medications",      [])
    state.setdefault("medication_log",   {})
    state.setdefault("cooked_history",   [])
    state.setdefault("pantry",           [])
    state.setdefault("nutrition_logs",   [])
    state.setdefault("profile", {
        "name": "", "age": "", "weight": "",
        "cuisine": "", "restrictions": "", "allergies": "",
        "goals_concerns": ""
    })
    for item in state["grocery_list"]:
        item.setdefault("delivery_date", None)
    return state

def save(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def default_state():
    return {
        "grocery_list":   [],
        "pantry":         [],            # <--- ADD THIS
        "nutrition_logs": [],            # <--- ADD THIS
        "profile": {
            "name": "", "age": "", "weight": "", 
            "cuisine": "", "restrictions": "", "allergies": "",
            "goals_concerns": ""
        },
        "timer":          {"active": False, "dish": "", "start_time": None, "duration_minutes": 0, "dismissed": False},
        "grocery_meta":   {"last_updated": None, "reminder_frequency_days": 3},
        "family_notes":   "",
        "elder_activity": {"last_opened": None, "last_timer_used": None},
        "medications":    [],
        "medication_log": {},
        "cooked_history": []
    }

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def days_since(iso_str):
    if not iso_str:
        return None
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 86400, 1)

# ── Pages ─────────────────────────────────────────────────────

@app.route("/")
def family():
    return render_template("family.html")

@app.route("/elder")
def elder():
    return render_template("elder.html")

@app.route("/chatbot")
def chatbot():
    return render_template("chatbot.html")

# ── Grocery ───────────────────────────────────────────────────

@app.route("/api/grocery", methods=["GET"])
def get_grocery():
    return jsonify(load()["grocery_list"])

@app.route("/api/grocery", methods=["POST"])
def add_item():
    data = request.json
    state = load()
    item = {
        "id":            str(uuid.uuid4()),
        "text":          data["text"],
        "amount":        data.get("amount", ""),
        "added_by":      data.get("added_by", "elder"),
        "claimed_by":    None,
        "delivery_date": None,
        "done":          False,
        "timestamp":     now_iso()
    }
    state["grocery_list"].append(item)
    state["grocery_meta"]["last_updated"] = now_iso()
    save(state)
    return jsonify(item), 201

@app.route("/api/grocery/clear-done", methods=["POST"])
def clear_done():
    state = load()
    state["grocery_list"] = [i for i in state["grocery_list"] if not i["done"]]
    save(state)
    return jsonify({"ok": True})

@app.route("/api/grocery/<item_id>", methods=["PATCH"])
def update_item(item_id):
    state = load()
    for item in state["grocery_list"]:
        if item["id"] == item_id:
            item.update(request.json)
            if "text" in request.json or "done" in request.json:
                state["grocery_meta"]["last_updated"] = now_iso()
            save(state)
            return jsonify(item)
    return jsonify({"error": "not found"}), 404

@app.route("/api/grocery/<item_id>", methods=["DELETE"])
def delete_item(item_id):
    state = load()
    state["grocery_list"] = [i for i in state["grocery_list"] if i["id"] != item_id]
    state["grocery_meta"]["last_updated"] = now_iso()
    save(state)
    return jsonify({"ok": True})

@app.route("/api/grocery/meta", methods=["GET"])
def get_meta():
    state = load()
    meta  = state["grocery_meta"]
    freq  = meta.get("reminder_frequency_days", 3)
    days  = days_since(meta.get("last_updated"))
    return jsonify({
        "last_updated":            meta.get("last_updated"),
        "reminder_frequency_days": freq,
        "days_since_update":       days,
        "overdue":                 days is None or days >= freq
    })

@app.route("/api/grocery/meta", methods=["POST"])
def set_meta():
    state = load()
    data  = request.json
    if "reminder_frequency_days" in data:
        state["grocery_meta"]["reminder_frequency_days"] = int(data["reminder_frequency_days"])
    save(state)
    return jsonify(state["grocery_meta"])

# ── Timer ─────────────────────────────────────────────────────

def timer_remaining_seconds(t):
    if not t.get("active") or not t.get("start_time"):
        return 0, False
    elapsed  = (datetime.now(timezone.utc) - datetime.fromisoformat(t["start_time"])).total_seconds()
    remaining = max(0, t["duration_minutes"] * 60 - elapsed)
    return int(remaining), remaining == 0

@app.route("/api/timer/start", methods=["POST"])
def start_timer():
    data  = request.json
    state = load()
    state["timer"] = {
        "active":           True,
        "dish":             data.get("dish", "food"),
        "start_time":       now_iso(),
        "duration_minutes": data.get("duration_minutes", 30),
        "dismissed":        False
    }
    state["elder_activity"]["last_timer_used"] = now_iso()
    save(state)
    return jsonify(state["timer"])

@app.route("/api/timer/dismiss", methods=["POST"])
def dismiss_timer():
    state = load()
    dish  = state["timer"].get("dish", "food")
    state["timer"].update({"active": False, "dismissed": True})

    entry = {
        "id":         str(uuid.uuid4()),
        "dish":       dish,
        "cooked_at":  now_iso(),
        "eat_by":     "Calculating…",
        "eat_by_reason": ""
    }
    state["cooked_history"].insert(0, entry)
    state["cooked_history"] = state["cooked_history"][:10]  # keep last 10
    save(state)

    # Get expiry from Gemini in background
    if gemini:
        def fetch_expiry(entry_id, dish_name):
            try:
                eat_by, reason = gemini.get_expiry(dish_name)
                s = load()
                for e in s["cooked_history"]:
                    if e["id"] == entry_id:
                        e["eat_by"]        = eat_by
                        e["eat_by_reason"] = reason
                        break
                save(s)
            except Exception as ex:
                logger.error(f"expiry thread error: {ex}")
        t = threading.Thread(target=fetch_expiry, args=(entry["id"], dish), daemon=True)
        t.start()

    return jsonify({"ok": True})

@app.route("/api/timer/reset", methods=["POST"])
def reset_timer():
    state = load()
    state["timer"] = {"active": False, "dish": "", "start_time": None, "duration_minutes": 0, "dismissed": False}
    save(state)
    return jsonify({"ok": True})

@app.route("/api/cooked", methods=["GET"])
def get_cooked():
    return jsonify(load()["cooked_history"])

# ── Medications ───────────────────────────────────────────────

def compute_med_status(med, medication_log):
    today   = today_str()
    log_key = f"{med['id']}_{today}"
    log     = medication_log.get(log_key, {})
    now_hhmm = datetime.now().strftime("%H:%M")

    if log.get("status") == "taken":
        return "taken", log_key
    if log.get("status") == "snoozed":
        if log.get("snoozed_until", 0) > datetime.now(timezone.utc).timestamp():
            return "snoozed", log_key
        # snooze expired → pending
    if log.get("status") == "pending" or now_hhmm >= med.get("time", "99:99"):
        return "pending", log_key
    return "upcoming", log_key

@app.route("/api/medications", methods=["GET"])
def get_medications():
    state  = load()
    meds   = [m for m in state["medications"] if m.get("active")]
    result = []
    for med in meds:
        status, _ = compute_med_status(med, state["medication_log"])
        result.append({**med, "status": status})
    return jsonify(result)

@app.route("/api/medications", methods=["POST"])
def add_medication():
    data  = request.json
    state = load()
    med   = {
        "id":     str(uuid.uuid4()),
        "name":   data["name"],
        "dosage": data["dosage"],
        "time":   data["time"],
        "active": True
    }
    state["medications"].append(med)
    save(state)
    return jsonify(med), 201

@app.route("/api/medications/<med_id>", methods=["DELETE"])
def delete_medication(med_id):
    state = load()
    for m in state["medications"]:
        if m["id"] == med_id:
            m["active"] = False
    save(state)
    return jsonify({"ok": True})

@app.route("/api/medications/taken", methods=["POST"])
def mark_taken():
    data    = request.json
    med_id  = data["med_id"]
    state   = load()
    log_key = f"{med_id}_{today_str()}"
    state["medication_log"][log_key] = {
        "status":   "taken",
        "taken_at": now_iso(),
        "snoozed_until": None
    }
    save(state)
    return jsonify({"ok": True})

@app.route("/api/medications/snooze", methods=["POST"])
def snooze_medication():
    data    = request.json
    med_id  = data["med_id"]
    state   = load()
    log_key = f"{med_id}_{today_str()}"
    state["medication_log"][log_key] = {
        "status":        "snoozed",
        "snoozed_until": datetime.now(timezone.utc).timestamp() + 1800  # 30 min
    }
    save(state)
    return jsonify({"ok": True})

@app.route("/api/medications/remind", methods=["POST"])
def remind_now():
    """Family forces a pending alert for a medication."""
    data    = request.json
    med_id  = data["med_id"]
    state   = load()
    log_key = f"{med_id}_{today_str()}"
    state["medication_log"][log_key] = {"status": "pending"}
    save(state)
    return jsonify({"ok": True})

# ── Elder ping + notes ────────────────────────────────────────

@app.route("/api/elder/ping", methods=["POST"])
def elder_ping():
    state = load()
    state["elder_activity"]["last_opened"] = now_iso()
    save(state)
    return jsonify({"ok": True})

@app.route("/api/notes", methods=["GET"])
def get_notes():
    return jsonify({"notes": load()["family_notes"]})

@app.route("/api/notes", methods=["POST"])
def set_notes():
    state = load()
    state["family_notes"] = request.json.get("notes", "")
    save(state)
    return jsonify({"ok": True})

# ── Status ────────────────────────────────────────────────────

@app.route("/api/status", methods=["GET"])
def get_status():
    state     = load()
    t         = state["timer"]
    remaining, expired = timer_remaining_seconds(t)
    meta      = state["grocery_meta"]
    freq      = meta.get("reminder_frequency_days", 3)
    days      = days_since(meta.get("last_updated"))

    meds   = [m for m in state["medications"] if m.get("active")]
    taken  = sum(1 for m in meds if compute_med_status(m, state["medication_log"])[0] == "taken")
    pending = sum(1 for m in meds if compute_med_status(m, state["medication_log"])[0] == "pending")

    return jsonify({
        "grocery_count":        len(state["grocery_list"]),
        "grocery_unclaimed":    sum(1 for i in state["grocery_list"] if not i["claimed_by"] and not i["done"]),
        "grocery_last_updated": meta.get("last_updated"),
        "grocery_days_since":   days,
        "grocery_overdue":      days is None or days >= freq,
        "reminder_frequency_days": freq,
        "timer_active":         t["active"],
        "timer_dish":           t["dish"],
        "timer_remaining":      remaining,
        "timer_expired":        expired,
        "timer_dismissed":      t["dismissed"],
        "family_notes":         state["family_notes"],
        "elder_last_opened":    state["elder_activity"].get("last_opened"),
        "elder_last_timer":     state["elder_activity"].get("last_timer_used"),
        "med_count":            len(meds),
        "med_taken":            taken,
        "med_pending":          pending,
        "gemini_ready":         gemini is not None
    })

@app.route("/api/chat", methods=["POST"])
def chat():
    if not gemini:
        return jsonify({"error": "Gemini API key not configured."}), 503
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    history = data.get("history", [])
    
    state = load()
    context = data.get("context", {})
    # Pass pantry and profile to Gemini so it knows what's available and who it's talking to
    context["pantry"]         = state.get("pantry", [])
    context["profile"]        = state.get("profile", {})
    context["nutrition_logs"] = state.get("nutrition_logs", [])

    try:
        reply = gemini.chat(history, message, context)
        if not reply:
            return jsonify({"error": "No response from AI. Please try again."}), 503

        # Process Nutrition and Pantry depletion if Gemini sent DATA
        if "DATA:" in reply:
            parts = reply.split("DATA:")
            main_reply = parts[0].strip()
            try:
                meta = json.loads(parts[1].strip())
                # Log Nutrition
                state.setdefault("nutrition_logs", []).append({
                    "timestamp": datetime.now().isoformat(),
                    "meal": message,
                    "cals": meta.get("calories"),
                    "prot": meta.get("protein")
                })
                # Deduct used items from pantry
                used = [i.lower() for i in meta.get("used_items", [])]
                if used:
                    state["pantry"] = [
                        p for p in state.get("pantry", [])
                        if not any(p["text"].lower() in u or u in p["text"].lower() for u in used)
                    ]
                save(state)
                reply = main_reply
            except Exception as parse_err:
                logger.warning(f"DATA parse error (reply kept as-is): {parse_err}")

        return jsonify({"response": reply})
    except Exception as e:
        logger.error(f"chat error: {e}")
        msg = "Daily AI quota reached. Please try again after midnight (Pacific Time)." \
              if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) \
              else "Something went wrong. Please try again."
        return jsonify({"error": msg}), 500



# ── Insights ──────────────────────────────────────────────────

@app.route("/api/insights", methods=["GET"])
def insights():
    state = load()
    grocery_texts = [i["text"] for i in state["grocery_list"] if not i["done"]]
    pantry_texts  = [i["text"] for i in state.get("pantry", [])]
    items = list(dict.fromkeys(grocery_texts + pantry_texts))  # deduplicated, order preserved
    if not gemini:
        return jsonify({"meal_plan": "", "suggestions": [], "items_used": items,
                        "note": "Add GEMINI_API_KEY to .env to enable insights."})
    result = gemini.get_insights(items, profile=state.get("profile", {}))
    result["items_used"] = items
    return jsonify(result)

# ── New Dashboard Endpoints ───────────────────────────────────

@app.route("/api/state", methods=["GET"])
def get_full_state():
    """Provides the full state for the family dashboard tabs."""
    state = load()
    return jsonify({
        "pantry": state.get("pantry", []),
        "nutrition_logs": state.get("nutrition_logs", [])
    })

@app.route("/api/groceries/deliver-all", methods=["POST"])
def deliver_all():
    """Moves all 'done' grocery items into the pantry."""
    state = load()
    # Initialize pantry if missing in old state.json
    if "pantry" not in state: state["pantry"] = []
    
    # Identify items to move
    to_pantry = [i for i in state["grocery_list"] if i.get("done")]
    remaining = [i for i in state["grocery_list"] if not i.get("done")]
    
    state["pantry"].extend(to_pantry)
    state["grocery_list"] = remaining
    
    save(state)
    return jsonify({"success": True, "count": len(to_pantry)})

# ──────────────────────────────────────────────────────────────

@app.route("/api/profile", methods=["GET"])
def get_profile():
    return jsonify(load().get("profile", {}))

@app.route("/api/profile", methods=["POST"])
def save_profile():
    """Saves the elder's background information and caregiver goals."""
    state = load()
    state["profile"] = request.json
    save(state)
    return jsonify({"success": True})

@app.route("/api/pantry", methods=["POST"])
def add_pantry_item():
    data = request.get_json(silent=True) or {}
    if not data.get("text"):
        return jsonify({"error": "text required"}), 400
    state = load()
    item = {
        "id":                  str(uuid.uuid4()),
        "text":                data["text"],
        "amount":              data.get("amount", ""),
        "added_by":            data.get("added_by", "elder"),
        "claimed_by":          None,
        "delivery_date":       None,
        "done":                True,
        "timestamp":           now_iso(),
        "expiry_date":         data.get("expiry_date", None),
        "estimated_calories":  data.get("estimated_calories", 0),
        "estimated_protein":   data.get("estimated_protein", 0),
    }
    state.setdefault("pantry", []).append(item)
    save(state)
    return jsonify(item), 201

def _parse_eat_by_to_iso(eat_by_text: str):
    """Best-effort parse of AI eat-by text to YYYY-MM-DD."""
    if not eat_by_text:
        return None
    for fmt in ["%A, %B %d, %Y", "%A, %B %d"]:
        try:
            parsed = datetime.strptime(eat_by_text, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=datetime.now().year)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None

@app.route("/api/pantry/add-cooked", methods=["POST"])
def add_cooked_to_pantry():
    """Deducts ingredients and adds the cooked dish (with AI expiry) to pantry."""
    data = request.get_json(silent=True) or {}
    dish = (data.get("dish") or "").strip()
    ingredients = [i.lower() for i in data.get("ingredients", [])]
    if not dish:
        return jsonify({"error": "dish required"}), 400

    state = load()

    # Deduct matching ingredients
    removed, kept = [], []
    for item in state.get("pantry", []):
        name = item["text"].lower()
        if ingredients and any(name in ing or ing in name for ing in ingredients):
            removed.append(item["text"])
        else:
            kept.append(item)
    state["pantry"] = kept

    # Get expiry + calorie info from AI
    info = {"eat_by": "", "reason": "", "calories": 0, "protein": 0}
    if gemini:
        try:
            info = gemini.get_cooked_info(dish)
        except Exception as e:
            logger.error(f"get_cooked_info error: {e}")

    expiry_date = _parse_eat_by_to_iso(info.get("eat_by", ""))

    new_item = {
        "id":                  str(uuid.uuid4()),
        "text":                dish,
        "amount":              "",
        "added_by":            "elder",
        "claimed_by":          None,
        "delivery_date":       None,
        "done":                True,
        "timestamp":           now_iso(),
        "expiry_date":         expiry_date,
        "eat_by_text":         info.get("eat_by", ""),
        "eat_by_reason":       info.get("reason", ""),
        "estimated_calories":  info.get("calories", 0),
        "estimated_protein":   info.get("protein", 0),
    }
    state["pantry"].insert(0, new_item)
    save(state)
    return jsonify({"removed": removed, "added": new_item, "eat_by": info.get("eat_by", "")})

@app.route("/api/pantry/consume", methods=["POST"])
def consume_pantry_item():
    """Mark pantry item as eaten — removes it and logs nutrition."""
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    state = load()
    item = next((i for i in state.get("pantry", []) if i["id"] == item_id), None)
    if not item:
        return jsonify({"error": "not found"}), 404
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "meal":      item["text"],
        "cals":      item.get("estimated_calories") or 0,
        "prot":      item.get("estimated_protein") or 0,
        "source":    "pantry",
    }
    state.setdefault("nutrition_logs", []).append(log_entry)
    state["pantry"] = [i for i in state["pantry"] if i["id"] != item_id]
    save(state)
    return jsonify(log_entry)

@app.route("/api/pantry/<item_id>", methods=["PATCH", "DELETE"])
def modify_pantry_item(item_id):
    state = load()
    if request.method == "DELETE":
        state["pantry"] = [i for i in state.get("pantry", []) if i["id"] != item_id]
        save(state)
        return jsonify({"ok": True})
    data = request.get_json(silent=True) or {}
    for item in state.get("pantry", []):
        if item["id"] == item_id:
            if "amount" in data:      item["amount"] = data["amount"]
            if "expiry_date" in data: item["expiry_date"] = data["expiry_date"]
            save(state)
            return jsonify(item)
    return jsonify({"error": "not found"}), 404

if __name__ == "__main__":
    app.run(debug=True, port=5001)