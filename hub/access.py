"""Resource-scoped permissions shared by the catalog and media routes."""
from __future__ import annotations

KINDS = ("spaces", "zones", "channels", "devices")
FEATURES = ("live", "archive_view", "archive_export", "create_devices", "edit_spaces")


def grants(user):
    if isinstance(user.get("grants"), dict):
        return {kind: user["grants"].get(kind, {}) for kind in KINDS}
    return {"spaces": {gid: user.get("group_access", {}).get(gid, "read")
                       for gid in user.get("group_ids", [])}, "zones": {}, "channels": {}, "devices": {}}


def features(user):
    result = {"live": True, "archive_view": bool(user.get("archive_access")),
              "archive_export": False, "create_devices": False, "edit_spaces": False}
    stored=user.get("permissions",{})
    result.update({key:stored[key] for key in FEATURES if key in stored})
    if "edit_spaces" not in stored:
        assigned=grants(user)
        result["edit_spaces"]=bool(stored.get("create_spaces") or any(value=="edit" for kind in ("spaces","zones") for value in assigned[kind].values()))
    if user.get("role") == "admin":
        result = {key: True for key in FEATURES}
    result["archive_export"] = bool(result["archive_export"] and result["archive_view"])
    return result


def level(user, kind, identifier):
    if not user or user.get("active") is False:
        return 0
    if user.get("role") == "admin":
        return 2
    value={"read":1,"edit":2}.get(grants(user).get(kind,{}).get(str(identifier)),0)
    return min(value,1) if kind in ("spaces","zones") and not features(user)["edit_spaces"] else value


def zone_level(user, space, zone_id):
    return max(level(user, "spaces", space["id"]), level(user, "zones", zone_id))


def source_level(user, camera, spaces):
    result = max(level(user, "channels", camera["id"]),
                 level(user, "devices", camera.get("recorder_id", "")))
    if result == 2:
        return result
    for space in spaces:
        for member in space.get("members", []):
            if member.get("channel_id") == camera["id"]:
                result = max(result, zone_level(user, space, member.get("zone_id")))
        if not space.get("members") and camera["id"] in space.get("camera_ids", []):
            result = max(result, level(user, "spaces", space["id"]))
    return result


def source_levels(user,cameras,spaces):
    if not user or user.get("active") is False:return {},{}
    if user.get("role")=="admin":levels={c["id"]:2 for c in cameras}
    else:
        scope=grants(user);rank={"read":1,"edit":2}
        levels={c["id"]:max(rank.get(scope["channels"].get(c["id"]),0),rank.get(scope["devices"].get(c.get("recorder_id")),0)) for c in cameras}
    memberships={}
    scope=grants(user);rank={"read":1,"edit":2};admin=user.get("role")=="admin"
    space_rank={"read":1,"edit":2 if features(user)["edit_spaces"] else 1}
    for space in spaces:
        root=2 if admin else space_rank.get(scope["spaces"].get(space["id"]),0)
        zone_values={z["id"]:2 if admin else max(root,space_rank.get(scope["zones"].get(z["id"]),0)) for z in space.get("zones",[])}
        if not root and not any(zone_values.values()):continue
        members=space.get("members") or [{"channel_id":cid} for cid in space.get("camera_ids",[])]
        for member in members:
            cid=member.get("channel_id");value=zone_values.get(member.get("zone_id"),root)
            if cid in levels and value:
                levels[cid]=max(levels[cid],value)
                memberships.setdefault(cid,[]).append(space)
    return levels,memberships


def manages_source(user, camera):
    """Organizing a space never silently grants deletion of shared infrastructure."""
    return max(level(user, "channels", camera["id"]),
               level(user, "devices", camera.get("recorder_id", ""))) == 2


def editor(user):
    return bool(user and user.get("active") is not False and
                (user.get("role") == "admin" or any(level(user,kind,key)==2 for kind,scope in grants(user).items() for key in scope) or
                 any(features(user)[k] for k in ("create_devices", "edit_spaces"))))


def normalize_user(user, reset_export=False):
    result = dict(user)
    result["grants"] = grants(user)
    result["permissions"] = features(user)
    if reset_export and user.get("role") != "admin":
        result["permissions"]["archive_export"] = False
    result.setdefault("active", True)
    # These projections keep 0.8 clients and backup readers understandable.
    result["group_ids"] = list(result["grants"]["spaces"])
    result["group_access"] = dict(result["grants"]["spaces"])
    result["archive_access"] = result["permissions"]["archive_view"]
    return result
