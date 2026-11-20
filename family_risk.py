
def assess_family_history(family_history):
    """
    Identify family-history patterns that may need
    further clinical evaluation.

    This is not a genetic diagnosis or probability calculator.
    """

    conditions = {}

    for member in family_history:
        disease = member.get("condition", "").strip().lower()

        if disease:
            conditions.setdefault(disease, []).append(member)

    findings = []

    for disease, members in conditions.items():

        generations = {
            member.get("generation")
            for member in members
            if member.get("generation")
        }

        if len(members) >= 2 or len(generations) >= 2:
            findings.append({
                "condition": disease.title(),
                "affected_members": len(members),
                "generations": len(generations),
                "indicator": "Family history pattern identified",
                "recommendation": (
                    "Consider discussing this family history "
                    "with a qualified healthcare professional."
                )
            })

    return {
        "total_conditions": len(conditions),
        "findings": findings,
        "message": (
            "Family history indicators are for awareness only. "
            "Clinical assessment may be needed."
        )
    }
