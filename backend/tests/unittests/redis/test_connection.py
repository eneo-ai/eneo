"""Unit tests for shared Redis connection helpers."""

from intric.redis.connection import build_arq_redis_settings, build_redis_pool_kwargs


def test_build_arq_redis_settings_uses_custom_values(test_settings):
    settings = test_settings.model_copy(
        update={
            "redis_db": 2,
            "redis_conn_timeout": 7,
            "redis_conn_retries": 9,
            "redis_conn_retry_delay": 3,
            "redis_retry_on_timeout": False,
            "redis_max_connections": 120,
        }
    )

    redis_settings = build_arq_redis_settings(settings)

    assert redis_settings.host == settings.redis_host
    assert redis_settings.port == settings.redis_port
    assert redis_settings.database == 2
    assert redis_settings.conn_timeout == 7
    assert redis_settings.conn_retries == 9
    assert redis_settings.conn_retry_delay == 3
    assert redis_settings.retry_on_timeout is False
    assert redis_settings.max_connections == 120


def test_build_redis_pool_kwargs_includes_expected_options(test_settings):
    settings = test_settings.model_copy(
        update={
            "redis_db": 3,
            "redis_conn_timeout": 6,
            "redis_retry_on_timeout": True,
            "redis_socket_keepalive": True,
            "redis_health_check_interval": 15,
            "redis_max_connections": 50,
        }
    )

    kwargs = build_redis_pool_kwargs(settings, decode_responses=False)

    assert kwargs["decode_responses"] is False
    assert kwargs["socket_connect_timeout"] == 6
    assert kwargs["retry_on_timeout"] is True
    assert kwargs["socket_keepalive"] is True
    assert kwargs["health_check_interval"] == 15
    assert kwargs["db"] == 3
    assert kwargs["max_connections"] == 50


def test_build_redis_pool_kwargs_omits_max_connections_when_none(test_settings):
    settings = test_settings.model_copy(update={"redis_max_connections": None})

    kwargs = build_redis_pool_kwargs(settings, decode_responses=True)

    assert kwargs["decode_responses"] is True
    assert "max_connections" not in kwargs
