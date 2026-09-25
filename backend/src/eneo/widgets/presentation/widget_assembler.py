# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from eneo.widgets.application.widget_service import WidgetView
from eneo.widgets.domain.widget_policy import WidgetPolicy
from eneo.widgets.presentation.widget_models import (
    WidgetPolicyPublic,
    WidgetPublic,
    WidgetTemplateLinkPublic,
)


class WidgetAssembler:
    @staticmethod
    def from_view(view: WidgetView) -> WidgetPublic:
        widget = view.widget
        assert widget.id is not None
        assert widget.created_at is not None and widget.updated_at is not None
        template = None
        if view.template is not None and view.template.id is not None:
            release = view.template.published
            template = WidgetTemplateLinkPublic(
                id=view.template.id,
                name=view.template.name,
                locked_groups=list(release.locked_groups) if release else [],
            )
        return WidgetPublic(
            id=widget.id,
            public_id=widget.public_id,
            space_id=widget.space_id,
            target_type=widget.target_type,
            target_id=widget.target_id,
            status=widget.status,
            token_generation=widget.token_generation,
            revision=widget.revision,
            name=widget.name,
            texts=widget.texts,
            theme=widget.theme,
            limits=widget.limits,
            privacy=widget.privacy,
            language=widget.language,
            allowed_origins=list(widget.allowed_origins),
            bot_protection=widget.bot_protection,
            show_sources=widget.show_sources,
            show_tool_activity=widget.show_tool_activity,
            activation_blockers=list(view.activation_blockers),
            template=template,
            created_by_user_id=widget.created_by_user_id,
            activated_by_user_id=widget.activated_by_user_id,
            activated_at=widget.activated_at,
            paused_at=widget.paused_at,
            created_at=widget.created_at,
            updated_at=widget.updated_at,
        )

    @staticmethod
    def from_policy(policy: WidgetPolicy) -> WidgetPolicyPublic:
        return WidgetPolicyPublic.model_validate(policy.model_dump())
