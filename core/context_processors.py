def business_payment_notice(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or user.is_superuser:
        return {}

    try:
        profile = user.profile
    except Exception:
        return {}
    if not profile.business_id:
        return {}

    business = profile.business
    if business.sync_payment_status():
        business.save(update_fields=["payment_status"])

    if business.payment_status == business.PAYMENT_OK:
        return {}

    return {
        "payment_notice": {
            "status": business.payment_status,
            "amount": business.amount_due,
            "due_date": business.due_date,
            "message": business.payment_notice,
        }
    }
