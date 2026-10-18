"""Session-state rules that prevent stale results: results are stored WITH the parcel they belong to, and are dropped when the
selected parcel changes. `state` is any dict-like (st.session_state in the app, a plain dict in tests)."""

RESULT_KEYS = ("vp_run", "vp_run_id", "vp_img", "vp_cmp", "vp_class", "vp_report", "vp_uploads")


def current_key(state):
    return state.get("vp_parcel_key")


def select_parcel(state, parcel_key) -> bool:
    """Select a parcel; clears every per-parcel result if it differs from the previous one. Returns True if it changed."""
    if state.get("vp_parcel_key") == parcel_key:
        return False
    for k in RESULT_KEYS:
        state.pop(k, None)
    state["vp_parcel_key"] = parcel_key
    return True


def store_run(state, run, run_id=None):
    if run.get("parcel_id") != current_key(state):
        raise ValueError("The run belongs to a different parcel than the one currently selected.")
    state["vp_run"], state["vp_run_id"] = run, run_id
    state.pop("vp_report", None)                       # a new run invalidates any report built earlier


def current_run(state):
    run = state.get("vp_run")
    return run if run and run.get("parcel_id") == current_key(state) else None


def store_imagery(state, parcel_key, payload):
    if parcel_key != current_key(state):
        raise ValueError("Imagery belongs to a different parcel than the one currently selected.")
    state["vp_img"] = {"parcel_id": parcel_key, **payload}
    state.pop("vp_report", None)


def current_imagery(state):
    img = state.get("vp_img")
    return img if img and img.get("parcel_id") == current_key(state) else None


def run_is_stale(run, settings, uploaded_ids=()) -> bool:
    """True if the settings (or the set of uploaded documents) differ from those used for the run."""
    return bool(run) and (run.get("settings") != settings or sorted(run.get("uploaded_documents", [])) != sorted(uploaded_ids))
