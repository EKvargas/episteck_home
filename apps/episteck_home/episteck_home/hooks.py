app_name = "episteck_home"
app_title = "Episteck Home"
app_publisher = "Episteck"
app_description = "Privacy-first household coordination core"
app_license = "Proprietary"

permission_query_conditions = {
    "Care Journey Item": "episteck_home.permissions.care_journey_item_query",
}

has_permission = {
    "Care Journey Item": "episteck_home.permissions.has_care_journey_item_permission",
}

# G1.6 trusted actor binding: establish delegated human context server-side, after
# Frappe has authenticated the machine caller. Never accepts a caller-supplied actor.
auth_hooks = [
    "episteck_home.identity.auth_hook.establish_delegated_context",
]
