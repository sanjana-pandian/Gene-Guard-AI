
import os
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify
)

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError, DuplicateKeyError

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from bson import ObjectId
from dotenv import load_dotenv

# Assessment modules
from services.family_risk import assess_family_history
from services.carrier_check import assess_carrier_compatibility
from services.report import generate_health_report


# ==================================================
# 1. APPLICATION CONFIGURATION
# ==================================================

load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "development-only-change-this-secret"
)

app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Enable secure cookies when deployed using HTTPS.
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("COOKIE_SECURE", "false").lower() == "true"
)

MONGO_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://127.0.0.1:27017"
)

DATABASE_NAME = os.getenv(
    "DATABASE_NAME",
    "geneguard_ai"
)


# ==================================================
# 2. MONGODB CONNECTION
# ==================================================

mongo_client = None
db = None

users_collection = None
assessments_collection = None

db_status = "Disconnected"

try:

    mongo_client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000
    )

    # Verify actual database connectivity.
    mongo_client.admin.command("ping")

    db = mongo_client[DATABASE_NAME]

    users_collection = db["users"]
    assessments_collection = db["assessments"]

    # Prevent duplicate registrations.
    users_collection.create_index(
        "email",
        unique=True
    )

    # Maintain one latest assessment per user and type.
    assessments_collection.create_index(
        [("user_id", 1), ("type", 1)],
        unique=True
    )

    db_status = "Connected"

    print("MongoDB connected successfully!")

except PyMongoError as error:

    print("MongoDB connection failed:", error)

    db_status = "Disconnected"


# ==================================================
# 3. TEMPORARY USER DATA
# ==================================================

# Only unsaved/current-session data is kept here.
# Permanent records are stored in MongoDB with consent.

assessment_cache = {}


def get_user_data():

    user_id = session.get("user_id")

    if not user_id:
        return {}

    return assessment_cache.setdefault(
        user_id,
        {}
    )


# ==================================================
# 4. DATABASE HELPER FUNCTIONS
# ==================================================

def check_database():

    global db_status

    if mongo_client is None:
        db_status = "Disconnected"
        return False

    try:

        mongo_client.admin.command("ping")

        db_status = "Connected"

        return True

    except PyMongoError as error:

        print("Database health check failed:", error)

        db_status = "Disconnected"

        return False


def save_assessment_record(
    assessment_type,
    data=None,
    result=None,
    extra=None
):

    if not check_database():
        return False

    user_id = session.get("user_id")

    if not user_id:
        return False

    document = {

        "user_id": user_id,

        "type": assessment_type,

        "data": data if data is not None else {},

        "result": result if result is not None else {},

        "updated_at": datetime.now(timezone.utc)

    }

    if extra:
        document.update(extra)

    try:

        assessments_collection.update_one(
            {
                "user_id": user_id,
                "type": assessment_type
            },
            {
                "$set": document,
                "$setOnInsert": {
                    "created_at": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )

        return True

    except PyMongoError as error:

        print(
            f"{assessment_type} saving error:",
            error
        )

        return False


def load_saved_assessment(assessment_type):

    if not check_database():
        return None

    user_id = session.get("user_id")

    if not user_id:
        return None

    try:

        return assessments_collection.find_one(
            {
                "user_id": user_id,
                "type": assessment_type
            }
        )

    except PyMongoError as error:

        print(
            f"{assessment_type} loading error:",
            error
        )

        return None


def delete_assessment_record(assessment_type):

    if not check_database():
        return False

    user_id = session.get("user_id")

    if not user_id:
        return False

    try:

        assessments_collection.delete_one(
            {
                "user_id": user_id,
                "type": assessment_type
            }
        )

        return True

    except PyMongoError as error:

        print(
            "Assessment deletion error:",
            error
        )

        return False


# ==================================================
# 5. FAMILY HISTORY STORAGE
# ==================================================

def load_saved_family_history(user_id):

    if not check_database():
        return None

    try:

        saved_record = assessments_collection.find_one(
            {
                "user_id": user_id,
                "type": "family_history"
            }
        )

        if saved_record:

            return {

                "history": saved_record.get("data", []),

                "result": saved_record.get("result", {})

            }

    except PyMongoError as error:

        print(
            "Family history loading error:",
            error
        )

    return None


def save_family_history(history):

    user_data = get_user_data()

    try:

        family_result = (
            assess_family_history(history)
            if history else {}
        )

    except Exception as error:

        print("Family assessment error:", error)

        return False

    user_data["family_history"] = history

    user_data["family_result"] = family_result

    if user_data.get("family_history_consent"):

        return save_assessment_record(
            assessment_type="family_history",
            data=history,
            result=family_result
        )

    return True


def validate_family_member(
    relationship,
    condition,
    generation
):

    if not relationship or not condition:
        return False

    if len(relationship) > 60:
        return False

    if len(condition) > 100:
        return False

    if len(generation) > 40:
        return False

    return True


# ==================================================
# 6. LOGIN PROTECTION
# ==================================================

def login_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:

            flash(
                "Please log in to access this page.",
                "warning"
            )

            return redirect(
                url_for("login")
            )

        return function(*args, **kwargs)

    return wrapper


# ==================================================
# 7. HOME PAGE
# ==================================================

@app.route("/")
def home():

    if "user_id" in session:

        return redirect(
            url_for("dashboard")
        )

    return render_template("index.html")


# ==================================================
# 8. USER REGISTRATION
# ==================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        if not check_database():

            flash(
                "Database unavailable. Please try again later.",
                "error"
            )

            return redirect(url_for("register"))

        name = request.form.get(
            "name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        confirm_password = request.form.get(
            "confirm_password", ""
        )

        if password != confirm_password:

            flash("Passwords do not match.", "error")

            return redirect(url_for("register"))

        if not name or len(name) > 100:

            flash("Please enter a valid name.", "error")

            return redirect(url_for("register"))

        if (
            not email
            or len(email) > 254
            or "@" not in email
        ):

            flash("Please enter a valid email address.", "error")

            return redirect(url_for("register"))

        if len(password) < 8 or len(password) > 128:

            flash(
                "Password must contain 8 to 128 characters.",
                "error"
            )

            return redirect(url_for("register"))

        try:

            user = {

                "name": name,

                "email": email,

                "password": generate_password_hash(password),

                "created_at": datetime.now(timezone.utc)

            }

            result = users_collection.insert_one(user)

            session.clear()

            session["user_id"] = str(result.inserted_id)

            session["user_name"] = name

            assessment_cache[session["user_id"]] = {}

            flash(
                "Registration successful!",
                "success"
            )

            return redirect(url_for("dashboard"))

        except DuplicateKeyError:

            flash(
                "This email is already registered.",
                "error"
            )

        except PyMongoError as error:

            print("Registration error:", error)

            flash(
                "Registration failed. Please try again.",
                "error"
            )

    return render_template(
        "register.html",
        mode="register"
    )


# ==================================================
# 9. USER LOGIN
# ==================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        if not check_database():

            flash("Database unavailable.", "error")

            return redirect(url_for("login"))

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        try:

            user = users_collection.find_one({
                "email": email
            })

            if user and check_password_hash(
                user["password"],
                password
            ):

                session.clear()

                session["user_id"] = str(user["_id"])

                session["user_name"] = user["name"]

                user_id = session["user_id"]

                assessment_cache[user_id] = {}

                user_data = get_user_data()

                # Restore family history.

                saved = load_saved_family_history(user_id)

                if saved:

                    user_data["family_history"] = saved["history"]

                    user_data["family_result"] = saved["result"]

                    user_data["family_history_consent"] = True

                # Restore carrier and career assessments.

                for assessment_type, cache_key in [

                    ("carrier_assessment", "carrier_result"),

                    ("career_assessment", "career_assessment_result")

                ]:

                    record = load_saved_assessment(
                        assessment_type
                    )

                    if record:

                        user_data[cache_key] = record.get(
                            "result", {}
                        )

                        if assessment_type == "carrier_assessment":

                            user_data["carrier_data"] = record.get(
                                "data", {}
                            )

                        elif assessment_type == "career_assessment":

                            user_data["career_assessment"] = record.get(
                                "data", {}
                            )

                flash(
                    "Welcome back!",
                    "success"
                )

                return redirect(url_for("dashboard"))

            flash(
                "Incorrect email or password.",
                "error"
            )

        except PyMongoError as error:

            print("Login error:", error)

            flash(
                "Unable to log in. Please try again.",
                "error"
            )

    return render_template(
        "register.html",
        mode="login"
    )


# ==================================================
# 10. USER LOGOUT
# ==================================================

@app.route("/logout")
@login_required
def logout():

    user_id = session.get("user_id")

    if user_id:

        assessment_cache.pop(
            user_id,
            None
        )

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(url_for("home"))


# ==================================================
# 11. DASHBOARD
# ==================================================

@app.route("/dashboard")
@login_required
def dashboard():

    user_data = get_user_data()

    latest_report = user_data.get(
        "latest_report"
    )

    check_database()

    return render_template(
        "dashboard.html",

        name=session.get("user_name"),

        report=latest_report,

        database_status=db_status
    )


# ==================================================
# 12. FAMILY HISTORY ASSESSMENT
# ==================================================

@app.route(
    "/family-history",
    methods=["GET", "POST"]
)
@login_required
def family_history():

    user_data = get_user_data()

    if request.method == "POST":

        members = request.form.getlist("member[]")

        conditions = request.form.getlist("condition[]")

        generations = request.form.getlist("generation[]")

        if not (
            len(members)
            == len(conditions)
            == len(generations)
        ):

            flash(
                "Please check your family history entries.",
                "error"
            )

            return redirect(url_for("family_history"))

        if len(members) > 30:

            flash(
                "Maximum 30 family records are allowed.",
                "error"
            )

            return redirect(url_for("family_history"))

        history = []

        for member, condition, generation in zip(
            members,
            conditions,
            generations
        ):

            member = member.strip()

            condition = condition.strip()

            generation = generation.strip()

            if not member or not condition:
                continue

            if not validate_family_member(
                member,
                condition,
                generation
            ):

                flash(
                    "One or more entries are invalid or too long.",
                    "error"
                )

                return redirect(url_for("family_history"))

            history.append({

                "relationship": member,

                "condition": condition,

                "generation": generation

            })

        if not history:

            flash(
                "Please enter at least one family history record.",
                "error"
            )

            return redirect(url_for("family_history"))

        try:

            family_result = assess_family_history(history)

        except Exception as error:

            print("Family assessment error:", error)

            flash(
                "Unable to complete the family assessment.",
                "error"
            )

            return redirect(url_for("family_history"))

        user_data["family_history"] = history

        user_data["family_result"] = family_result

        consent = (
            request.form.get("save_consent") == "yes"
        )

        user_data["family_history_consent"] = consent

        if consent:

            if check_database():

                saved = save_assessment_record(
                    assessment_type="family_history",
                    data=history,
                    result=family_result
                )

                if not saved:

                    flash(
                        "Assessment completed, but permanent saving failed.",
                        "warning"
                    )

            else:

                flash(
                    "Assessment completed, but MongoDB is unavailable.",
                    "warning"
                )

        else:

            # Delete previously saved data when consent is withdrawn.

            if check_database():

                if not delete_assessment_record("family_history"):

                    flash(
                        "Could not remove the previously saved record.",
                        "warning"
                    )

            else:

                flash(
                    "MongoDB is unavailable. Previously saved data could not be removed.",
                    "warning"
                )

        flash(
            "Family history assessment completed!",
            "success"
        )

        return redirect(url_for("family_tree"))

    return render_template("family_history.html")


# ==================================================
# 13. FAMILY TREE
# ==================================================

@app.route("/family-tree")
@login_required
def family_tree():

    user_data = get_user_data()

    if "family_history" not in user_data:

        saved = load_saved_family_history(
            session["user_id"]
        )

        if saved:

            user_data["family_history"] = saved["history"]

            user_data["family_result"] = saved["result"]

            user_data["family_history_consent"] = True

    history = user_data.get(
        "family_history",
        []
    )

    result = user_data.get(
        "family_result",
        {}
    )

    return render_template(
        "family_tree.html",

        history=history,

        result=result
    )


# ==================================================
# 14. ADD FAMILY MEMBER
# ==================================================

@app.route(
    "/family-tree/add",
    methods=["POST"]
)
@login_required
def add_family_member():

    relationship = request.form.get(
        "relationship", ""
    ).strip()

    condition = request.form.get(
        "condition", ""
    ).strip()

    generation = request.form.get(
        "generation", ""
    ).strip()

    if not validate_family_member(
        relationship,
        condition,
        generation
    ):

        flash(
            "Please enter valid family member details.",
            "error"
        )

        return redirect(url_for("family_tree"))

    user_data = get_user_data()

    history = user_data.get(
        "family_history",
        []
    )

    if len(history) >= 30:

        flash(
            "Maximum 30 family records are allowed.",
            "error"
        )

        return redirect(url_for("family_tree"))

    history.append({

        "relationship": relationship,

        "condition": condition,

        "generation": generation

    })

    saved = save_family_history(history)

    if not saved:

        flash(
            "Member added to the current session, but permanent saving failed.",
            "warning"
        )

    else:

        flash(
            "Family member added successfully!",
            "success"
        )

    return redirect(url_for("family_tree"))


# ==================================================
# 15. EDIT FAMILY MEMBER
# ==================================================

@app.route(
    "/family-tree/edit/<int:index>",
    methods=["POST"]
)
@login_required
def edit_family_member(index):

    relationship = request.form.get(
        "relationship", ""
    ).strip()

    condition = request.form.get(
        "condition", ""
    ).strip()

    generation = request.form.get(
        "generation", ""
    ).strip()

    if not validate_family_member(
        relationship,
        condition,
        generation
    ):

        flash(
            "Please enter valid family member details.",
            "error"
        )

        return redirect(url_for("family_tree"))

    user_data = get_user_data()

    history = user_data.get(
        "family_history",
        []
    )

    if index < 0 or index >= len(history):

        flash(
            "Family member not found.",
            "error"
        )

        return redirect(url_for("family_tree"))

    history[index] = {

        "relationship": relationship,

        "condition": condition,

        "generation": generation

    }

    saved = save_family_history(history)

    if not saved:

        flash(
            "Changes made in the current session, but permanent saving failed.",
            "warning"
        )

    else:

        flash(
            "Family member updated successfully!",
            "success"
        )

    return redirect(url_for("family_tree"))


# ==================================================
# 16. DELETE FAMILY MEMBER
# ==================================================

@app.route(
    "/family-tree/delete/<int:index>",
    methods=["POST"]
)
@login_required
def delete_family_member(index):

    user_data = get_user_data()

    history = user_data.get(
        "family_history",
        []
    )

    if index < 0 or index >= len(history):

        flash(
            "Family member not found.",
            "error"
        )

        return redirect(url_for("family_tree"))

    history.pop(index)

    saved = save_family_history(history)

    if not saved:

        flash(
            "Member deleted from the current session, but permanent saving failed.",
            "warning"
        )

    else:

        flash(
            "Family member deleted successfully!",
            "success"
        )

    return redirect(url_for("family_tree"))


# ==================================================
# 17. GENETIC CARRIER COMPATIBILITY
# ==================================================

@app.route(
    "/carrier-assessment",
    methods=["GET", "POST"]
)
@login_required
def carrier_assessment():

    if request.method == "POST":

        condition = request.form.get(
            "condition", ""
        ).strip()

        status_a = request.form.get(
            "status_a", ""
        ).strip().lower()

        status_b = request.form.get(
            "status_b", ""
        ).strip().lower()

        confirmed_a = (
            request.form.get("confirmed_a") == "yes"
        )

        confirmed_b = (
            request.form.get("confirmed_b") == "yes"
        )

        if not condition or len(condition) > 100:

            flash(
                "Please enter a valid condition.",
                "error"
            )

            return redirect(url_for("carrier_assessment"))

        valid_statuses = {
            "carrier",
            "not_carrier",
            "affected"
        }

        if (
            status_a not in valid_statuses
            or status_b not in valid_statuses
        ):

            flash(
                "Please select valid genetic test results.",
                "error"
            )

            return redirect(url_for("carrier_assessment"))

        person_a = {

            "condition": condition,

            "status": status_a,

            "confirmed": confirmed_a

        }

        person_b = {

            "condition": condition,

            "status": status_b,

            "confirmed": confirmed_b

        }

        try:

            carrier_result = assess_carrier_compatibility(
                person_a,
                person_b
            )

        except Exception as error:

            print("Carrier assessment error:", error)

            flash(
                "Unable to complete carrier assessment.",
                "error"
            )

            return redirect(url_for("carrier_assessment"))

        carrier_result["condition"] = condition

        user_data = get_user_data()

        user_data["carrier_result"] = carrier_result

        user_data["carrier_data"] = {

            "condition": condition,

            "person_a": person_a,

            "person_b": person_b

        }

        if request.form.get("save_consent") == "yes":

            if check_database():

                saved = save_assessment_record(
                    assessment_type="carrier_assessment",
                    data=user_data["carrier_data"],
                    result=carrier_result
                )

                if not saved:

                    flash(
                        "Assessment completed, but saving failed.",
                        "warning"
                    )

            else:

                flash(
                    "Assessment completed, but MongoDB is unavailable.",
                    "warning"
                )

        flash(
            "Carrier compatibility assessment completed!",
            "success"
        )

        return redirect(url_for("health_report"))

    return render_template("carrier_assessment.html")


# ==================================================
# 18. CAREER & HEALTH ASSESSMENT
# ==================================================

@app.route(
    "/career-assessment",
    methods=["GET", "POST"]
)
@login_required
def career_assessment():

    user_data = get_user_data()

    if request.method == "POST":

        age = request.form.get("age", "").strip()

        gender = request.form.get("gender", "").strip()

        occupation = request.form.get("occupation", "").strip()

        activity = request.form.get("activity", "").strip()

        medical_history = request.form.get(
            "medical_history", ""
        ).strip()

        sleep = request.form.get("sleep", "").strip()

        stress = request.form.get("stress", "").strip()

        family_history = request.form.get(
            "family_history", ""
        ).strip()

        family_conditions = request.form.get(
            "family_conditions", ""
        ).strip()

        exercise = request.form.get("exercise", "").strip()

        diet = request.form.get("diet", "").strip()

        fatigue = request.form.get("fatigue", "").strip()

        checkup = request.form.get("checkup", "").strip()

        additional_info = request.form.get(
            "additional_info", ""
        ).strip()

        # Age validation.

        try:

            age = int(age)

        except (ValueError, TypeError):

            flash("Please enter a valid age.", "error")

            return redirect(url_for("career_assessment"))

        if age < 1 or age > 120:

            flash(
                "Age must be between 1 and 120.",
                "error"
            )

            return redirect(url_for("career_assessment"))

        # Allowed input values.

        allowed_values = {

            "occupation": {
                "Student",
                "Working Professional",
                "Self Employed",
                "Other"
            },

            "activity": {
                "Low",
                "Moderate",
                "High"
            },

            "sleep": {
                "Less than 5 hours",
                "5-7 hours",
                "7-9 hours",
                "More than 9 hours"
            },

            "stress": {
                "Low",
                "Moderate",
                "High"
            },

            "family_history": {
                "Yes",
                "No",
                "Unknown"
            },

            "exercise": {
                "Daily",
                "3-4 times a week",
                "Occasionally",
                "Never"
            },

            "diet": {
                "Balanced",
                "Mostly Healthy",
                "Irregular",
                "Unhealthy"
            },

            "fatigue": {
                "Rarely",
                "Sometimes",
                "Frequently",
                "Almost Daily"
            },

            "checkup": {
                "Regularly",
                "Once a year",
                "Only when needed",
                "Never"
            }

        }

        submitted_values = {

            "occupation": occupation,

            "activity": activity,

            "sleep": sleep,

            "stress": stress,

            "family_history": family_history,

            "exercise": exercise,

            "diet": diet,

            "fatigue": fatigue,

            "checkup": checkup

        }

        for field, allowed in allowed_values.items():

            if submitted_values[field] not in allowed:

                flash(
                    f"Please select a valid {field.replace('_', ' ')} option.",
                    "error"
                )

                return redirect(url_for("career_assessment"))

        if (
            len(gender) > 50
            or len(medical_history) > 2000
            or len(family_conditions) > 2000
            or len(additional_info) > 2000
        ):

            flash(
                "Please check your text responses.",
                "error"
            )

            return redirect(url_for("career_assessment"))

        career_data = {

            "age": age,

            "gender": gender,

            "occupation": occupation,

            "activity": activity,

            "medical_history": medical_history,

            "sleep": sleep,

            "stress": stress,

            "family_history": family_history,

            "family_conditions": family_conditions,

            "exercise": exercise,

            "diet": diet,

            "fatigue": fatigue,

            "checkup": checkup,

            "additional_info": additional_info

        }

        # Informational findings.

        findings = []

        if exercise in {"Daily", "3-4 times a week"}:

            findings.append(
                "Your reported exercise frequency indicates regular physical activity."
            )

        else:

            findings.append(
                "Consider discussing a suitable physical activity routine with a healthcare professional."
            )

        if sleep == "7-9 hours":

            findings.append(
                "Your reported sleep duration is within a commonly recommended adult sleep range."
            )

        elif sleep == "Less than 5 hours":

            findings.append(
                "Your reported sleep duration is relatively short. Consider discussing persistent sleep difficulties with a healthcare professional."
            )

        else:

            findings.append(
                "Maintain a consistent sleep routine and monitor your sleep quality."
            )

        if stress == "High":

            findings.append(
                "You reported a high stress level. Consider healthy stress-management strategies or professional support."
            )

        elif stress == "Moderate":

            findings.append(
                "Continue monitoring stress and maintain regular relaxation activities."
            )

        else:

            findings.append(
                "Continue maintaining healthy approaches to managing stress."
            )

        if fatigue in {"Frequently", "Almost Daily"}:

            findings.append(
                "Frequent fatigue should be discussed with a qualified healthcare professional."
            )

        if family_history == "Yes":

            findings.append(
                "You reported a family history of health conditions. Consider discussing the relevant details with a healthcare professional."
            )

        elif family_history == "Unknown":

            findings.append(
                "Your family health history is currently unknown. Gather information where possible."
            )

        else:

            findings.append(
                "You reported no known family history of hereditary or chronic conditions."
            )

        if diet in {"Balanced", "Mostly Healthy"}:

            findings.append(
                "Your reported dietary habits indicate attention to healthy eating."
            )

        else:

            findings.append(
                "Consider discussing balanced nutrition and suitable dietary changes with a qualified professional."
            )

        if checkup in {"Never", "Only when needed"}:

            findings.append(
                "Discuss appropriate preventive health checkups with a healthcare professional."
            )

        assessment_result = {

            "title": "Career & Health Assessment",

            "age": age,

            "occupation": occupation,

            "activity_level": activity,

            "findings": findings,

            "status": "Completed",

            "disclaimer": (
                "These findings summarize your responses. "
                "They are not a medical diagnosis or a genetic risk prediction."
            )

        }

        user_data["career_assessment"] = career_data

        user_data["career_assessment_result"] = assessment_result

        if request.form.get("save_consent") == "yes":

            if check_database():

                saved = save_assessment_record(
                    assessment_type="career_assessment",
                    data=career_data,
                    result=assessment_result
                )

                if not saved:

                    flash(
                        "Assessment completed, but permanent saving failed.",
                        "warning"
                    )

            else:

                flash(
                    "Assessment completed, but MongoDB is unavailable.",
                    "warning"
                )

        flash(
            "Career and health assessment completed successfully!",
            "success"
        )

        return render_template(
            "career_assessment.html",
            assessment_result=assessment_result
        )

    previous_result = user_data.get(
        "career_assessment_result"
    )

    return render_template(
        "career_assessment.html",
        assessment_result=previous_result
    )


# ==================================================
# 19. COMBINED HEALTH REPORT
# ==================================================

@app.route("/report")
@login_required
def health_report():

    user_data = get_user_data()

    family_result = user_data.get(
        "family_result",
        {
            "total_conditions": 0,
            "findings": []
        }
    )

    carrier_result = user_data.get(
        "carrier_result",
        {}
    )

    # Restore saved results when the current session
    # does not contain them.

    if not family_result:

        saved = load_saved_family_history(
            session["user_id"]
        )

        if saved:

            family_result = saved["result"]

            user_data["family_result"] = family_result

    if not carrier_result:

        saved_carrier = load_saved_assessment(
            "carrier_assessment"
        )

        if saved_carrier:

            carrier_result = saved_carrier.get(
                "result", {}
            )

            user_data["carrier_result"] = carrier_result

    try:

        report = generate_health_report(

            user_name=session.get(
                "user_name",
                "User"
            ),

            family_result=family_result,

            carrier_result=carrier_result

        )

    except Exception as error:

        print("Health report error:", error)

        flash(
            "Unable to generate your health report.",
            "error"
        )

        return redirect(url_for("dashboard"))

    user_data["latest_report"] = report

    return render_template(
        "report.html",
        report=report
    )


# ==================================================
# 20. MONGODB STATUS API
# ==================================================

@app.route("/api/status")
def api_status():

    connected = check_database()

    return jsonify({

        "application": "GeneGuard AI",

        "status": "Running",

        "database": db_status,

        "database_name": DATABASE_NAME,

        "mongodb_connected": connected

    }), 200 if connected else 503


# ==================================================
# 21. ERROR HANDLERS
# ==================================================

@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "index.html"
    ), 404


@app.errorhandler(413)
def request_too_large(error):

    return "Uploaded request is too large.", 413


# ==================================================
# 22. APPLICATION SHUTDOWN
# ==================================================

import atexit


@atexit.register
def close_mongodb():

    if mongo_client is not None:

        mongo_client.close()

        print("MongoDB connection closed.")


# ==================================================
# 23. RUN APPLICATION
# ==================================================

if __name__ == "__main__":

    print("\n================================")

    print("         GENEGUARD AI")

    print("================================")

    print("Application: Running")

    print("Database:", db_status)

    print("URL: http://127.0.0.1:5000")

    print("================================\n")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
