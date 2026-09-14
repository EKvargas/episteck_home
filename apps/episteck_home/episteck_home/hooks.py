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
