from __future__ import annotations

from intric.flows.flow_access_policy import (
    FlowApiAction,
    require_flow_action,
    user_can_perform_flow_action,
)
from intric.users.user import UserInDB


def user_can_view_flows(user: UserInDB) -> bool:
    return user_can_perform_flow_action(user, FlowApiAction.VIEW)


def user_can_run_flows(user: UserInDB) -> bool:
    return user_can_perform_flow_action(user, FlowApiAction.RUN)


def user_can_manage_flows(user: UserInDB) -> bool:
    return user_can_perform_flow_action(user, FlowApiAction.EDIT)


def user_can_use_flow_ai_builder(user: UserInDB) -> bool:
    return user_can_perform_flow_action(
        user, FlowApiAction.BUILDER_SESSION_CREATE
    )


def user_can_view_flow_trace(user: UserInDB) -> bool:
    return user_can_perform_flow_action(user, FlowApiAction.TRACE_VIEW)


def ensure_can_view_flows(user: UserInDB) -> None:
    require_flow_action(user, FlowApiAction.VIEW)


def ensure_can_run_flows(user: UserInDB) -> None:
    require_flow_action(user, FlowApiAction.RUN)


def ensure_can_manage_flows(user: UserInDB) -> None:
    require_flow_action(user, FlowApiAction.EDIT)


def ensure_can_use_flow_ai_builder(user: UserInDB) -> None:
    require_flow_action(user, FlowApiAction.BUILDER_SESSION_CREATE)


def ensure_can_view_flow_trace(user: UserInDB) -> None:
    require_flow_action(user, FlowApiAction.TRACE_VIEW)
