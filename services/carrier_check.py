
def assess_carrier_compatibility(person_a, person_b):
    """
    Compare confirmed carrier test results for an
    autosomal recessive inherited condition.

    This tool provides educational information only.
    """

    condition_a = person_a.get("condition", "").strip().lower()
    condition_b = person_b.get("condition", "").strip().lower()

    status_a = person_a.get("status", "").strip().lower()
    status_b = person_b.get("status", "").strip().lower()

    confirmed_a = person_a.get("confirmed", False)
    confirmed_b = person_b.get("confirmed", False)

    # Check whether both results are confirmed
    if not confirmed_a or not confirmed_b:
        return {
            "status": "Incomplete",
            "message": "Both individuals need confirmed genetic test results."
        }

    # Check whether the conditions match
    if not condition_a or condition_a != condition_b:
        return {
            "status": "Not comparable",
            "message": "Both results must refer to the same condition."
        }

    valid_statuses = {"carrier", "not_carrier", "affected"}

    if status_a not in valid_statuses or status_b not in valid_statuses:
        return {
            "status": "Invalid",
            "message": "Please provide valid genetic test result categories."
        }

    # This simple calculation applies only to
    # autosomal recessive inheritance.
    if status_a == "affected" or status_b == "affected":
        return {
            "status": "Clinical review required",
            "message": (
                "At least one individual has an affected result. "
                "A genetic counsellor should review both results."
            )
        }

    # Both individuals are carriers
    if status_a == "carrier" and status_b == "carrier":
        return {
            "status": "Carrier match identified",
            "affected_risk": "25%",
            "carrier_risk": "50%",
            "unaffected_non_carrier_risk": "25%",
            "message": (
                "For each pregnancy, there is a 25% chance of an "
                "affected child under the usual autosomal recessive model."
            ),
            "recommendation": (
                "Consult a qualified genetic counsellor to discuss "
                "reproductive options."
            )
        }

    # Only one individual is a carrier
    if status_a != status_b:
        return {
            "status": "One carrier identified",
            "affected_risk": "0%",
            "carrier_risk": "50%",
            "unaffected_non_carrier_risk": "50%",
            "message": (
                "Under the standard autosomal recessive model, "
                "no affected offspring are expected from this "
                "specific condition when the other individual "
                "has a confirmed non-carrier result."
            )
        }

    # Both individuals are confirmed non-carriers
    return {
        "status": "No carrier match identified",
        "affected_risk": "0%",
        "carrier_risk": "0%",
        "unaffected_non_carrier_risk": "100%",
        "message": (
            "Neither individual was identified as a carrier "
            "in the reported tests. Residual risk may remain."
        )
    }
