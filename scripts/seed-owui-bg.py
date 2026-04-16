import os, sys, uuid, traceback
sys.path.insert(0, "/app/backend")
try:
    from open_webui.models.users import Users
    from open_webui.models.auths import Auths
    from open_webui.utils.auth import get_password_hash
    u = os.environ["BG_USER"]; p = os.environ["BG_PASS"]
    email = f"{u}@insidellm.local"
    pw = get_password_hash(p)
    ex = Users.get_user_by_email(email)
    if ex:
        Users.update_user_role_by_id(ex.id, "admin")
        try: Auths.update_user_password_by_id(ex.id, pw)
        except Exception: Auths.update_password_by_id(ex.id, pw)
        print("updated", ex.id)
    else:
        uid = str(uuid.uuid4())
        try:
            Auths.insert_new_auth(id=uid, email=email, password=pw,
                name="InsideLLM Break-Glass", profile_image_url="/user.png", role="admin")
        except TypeError:
            Auths.insert_new_auth(email=email, password=pw,
                name="InsideLLM Break-Glass", profile_image_url="/user.png", role="admin")
        print("created", email)
except Exception as e:
    traceback.print_exc(); sys.exit(1)
