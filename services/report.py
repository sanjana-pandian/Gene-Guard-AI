
from datetime import datetime


def extract_result(assessment):
    """
    Extract assessment results from either a MongoDB
    document or a result dictionary.
    """

    if not isinstance(assessment, dict):
        return {}

    result = assessment.get("result")

    if isinstance(result, dict):
        return result

    return assessment


def generate_health_report(
    user_name,
    family_result,
    carrier_result=None
):
    """
    Generate a combined GeneGuard AI health assessment report.
    """

    # Extract assessment data
    family_result = extract_result(family_result)
    carrier_result = extract_result(carrier_result)

    # Validate family findings
    family_findings = family_result.get("findings", [])

    if not isinstance(family_findings, list):
        family_findings = []

    # Generate recommendations
    recommendations = []

    # ----------------------------------
    # 1. FAMILY HISTORY RECOMMENDATIONS
    # ----------------------------------

    for finding in family_findings:

        if not isinstance(finding, dict):
            continue

        condition = finding.get(
            "condition",
            "Unknown condition"
        )

        recommendations.append({
            "category": "Family History",
            "condition": condition,
            "action": (
                "Discuss this family history with a "
                "qualified healthcare professional."
            )
        })

    # ----------------------------------
    # 2. CARRIER ASSESSMENT
    # ----------------------------------

    carrier_status = carrier_result.get(
        "status",
        "Not assessed"
    )

    if carrier_status == "Carrier match identified":

        recommendations.append({
            "category": "Genetic Carrier Assessment",
            "condition": carrier_result.get(
                "condition",
                "Reported condition"
            ),
            "action": (
                "Consult a qualified genetic counsellor "
                "to discuss reproductive risks and options."
            )
        })

    elif carrier_status == "Incomplete":

        recommendations.append({
            "category": "Genetic Carrier Assessment",
            "condition": "Incomplete results",
            "action": (
                "Obtain and verify the required genetic "
                "test results before interpreting compatibility."
            )
        })

    elif carrier_status == "Not assessed":

        recommendations.append({
            "category": "Genetic Carrier Assessment",
            "condition": "Assessment pending",
            "action": (
                "Complete the genetic carrier assessment "
                "if recommended by a qualified healthcare professional."
            )
        })

    else:

        recommendations.append({
            "category": "Preventive Healthcare",
            "condition": "General guidance",
            "action": (
                "Maintain regular healthcare checkups and "
                "discuss appropriate screening with a clinician."
            )
        })

    # ----------------------------------
    # 3. ASSESSMENT COMPLETION STATUS
    # ----------------------------------

    family_submitted = bool(family_result)
    carrier_submitted = bool(carrier_result)

    if family_submitted and carrier_submitted:
        report_status = "REPORT GENERATED"

    else:
        report_status = "ASSESSMENT INCOMPLETE"

    # ----------------------------------
    # 4. FINAL HEALTH REPORT
    # ----------------------------------

    report = {

        "project": "GeneGuard AI",

        "patient_name": user_name,

        "generated_at": datetime.now().strftime(
            "%d-%m-%Y %H:%M:%S"
        ),

        "status": report_status,

        "family_history": {

            "total_conditions": family_result.get(
                "total_conditions",
                len(family_findings)
            ),

            "findings": family_findings
        },

        "carrier_assessment": carrier_result,

        "recommendations": recommendations,

        "disclaimer": (
            "This report is for educational purposes only. "
            "It is not a medical diagnosis or a substitute "
            "for professional genetic counselling."
        )
    }

    return report


