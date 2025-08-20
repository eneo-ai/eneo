import json
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from intric.database.database import sessionmanager
from intric.jobs.job_manager import job_manager
from intric.main.aiohttp_client import aiohttp_client
from intric.main.config import SETTINGS
from intric.server.dependencies.ai_models import init_models
from intric.server.dependencies.modules import init_modules
from intric.server.dependencies.predefined_roles import init_predefined_roles
from intric.server.websockets.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    yield
    await shutdown()


async def validate_and_display_config():
    """
    Validate configuration and display startup summary.
    This runs once during application startup to check configuration
    and provide visibility into what's enabled/disabled.
    """
    try:
        # Run configuration validation
        config_status = SETTINGS.check()
        
        from datetime import datetime
        import os
        
        # Display configuration summary with masked secrets
        summary = SETTINGS.get_summary(mask_secrets=True)
        
        # Display configuration summary using print to ensure visibility
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pid = os.getpid()
        
        print("─" * 80)
        print(f"🚀 ENEO Backend • {summary['app_version']} • {summary['environment']} • {timestamp} • pid {pid}")
        print("─" * 80)
        
        # Count enabled/disabled items for summaries
        enabled_models = [k for k, v in summary['ai_models'].items() if v not in ["Not set", "Disabled"]]
        total_models = len([k for k, v in summary['ai_models'].items() if v != "Disabled"])
        enabled_features = [k for k, v in summary['features'].items() if v]
        total_features = len(summary['features'])
        
        # Mask database URL properly
        def mask_db_url(url: str) -> str:
            if "@" in url and "://" in url:
                scheme, rest = url.split("://", 1)
                if "@" in rest:
                    creds, host_db = rest.split("@", 1)
                    if ":" in creds:
                        user, _ = creds.split(":", 1)
                        return f"{scheme}://{user}:****@{host_db}"
            return url
        
        print("📋 Summary")
        print(f"   Version            {summary['app_version']}")
        print(f"   Environment        {summary['environment']}")
        print("")
        
        # Display AI model configuration with counts
        print(f"🤖 AI Providers       {len(enabled_models)}/{total_models} configured")
        for model, status in summary['ai_models'].items():
            if status == "Disabled":
                continue  # Skip disabled models to reduce noise
            if status not in ["Not set", "Disabled"]:
                print(f"   ✅ {model:<12} configured")
            else:
                print(f"   ❌ {model:<12} not set")
        print("")
        
        # Display feature flags with counts
        print(f"🎛️  Features           {len(enabled_features)}/{total_features} enabled")
        if enabled_features:
            enabled_display = "   ✅ " + "  ✅ ".join(enabled_features)
            print(enabled_display)
        disabled_features = [k for k, v in summary['features'].items() if not v]
        if disabled_features:
            disabled_display = "   ❌ " + "  ❌ ".join(disabled_features)
            print(disabled_display)
        print("")
        
        # Display infrastructure with masked URLs
        print("🔧 Infrastructure")
        print(f"   Database          {mask_db_url(summary['database'])}")
        print(f"   Redis             {summary['redis']}")
        print("")
        
        # Display auth providers
        print("🔐 Authentication")
        for provider, status in summary['auth_providers'].items():
            status_icon = "✅" if status == "Configured" else "❌"
            print(f"   {provider:<13} {status_icon} {status}")
        print("")
        
        # Handle warnings
        if config_status['warnings']:
            print("⚠️  Warnings")
            for warning in config_status['warnings']:
                print(f"   • {warning}")
            print("")
        
        # Handle errors
        if config_status['errors']:
            print("❌ Errors")
            for error in config_status['errors']:
                print(f"   • {error}")
            print("")
            
            # In production, exit on configuration errors
            if not SETTINGS.dev:
                print("Exiting due to configuration errors in production mode")
                sys.exit(1)
            else:
                print("Continuing in development mode despite configuration errors")
        
        # Validation status and next steps
        if not config_status['errors']:
            print("✅ Validation         OK")
            if enabled_features:
                print(f"   Active features   {', '.join(enabled_features)}")
            print("")
            
            # Next steps section
            next_steps = []
            if not enabled_models:
                next_steps.append("Set API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.) to enable AI models")
            if not summary['auth_providers']['mobilityguard'] == "Configured":
                next_steps.append("Configure MOBILITYGUARD_* variables for authentication")
            
            if next_steps:
                print("💡 Next Steps")
                for step in next_steps:
                    print(f"   • {step}")
                print("")
        
        print("─" * 80)
        
        # Structured logging for monitoring systems
        config_log_data = {
            "event": "config_loaded",
            "timestamp": config_status['timestamp'],
            "status": "healthy" if not config_status['errors'] else ("degraded" if not config_status['errors'] and config_status['warnings'] else "unhealthy"),
            "config_hash": config_status['config_hash'],
            "app_version": summary['app_version'],
            "environment": summary['environment'],
            "errors": len(config_status['errors']),
            "warnings": len(config_status['warnings']),
            "unknown_vars": len(config_status['unknown_vars']),
            "features_enabled": len(enabled_features),
            "models_configured": len(enabled_models),
            "pid": pid
        }
        
        # Log structured data as JSON for monitoring systems
        print(f"ENEO_CONFIG_EVENT: {json.dumps(config_log_data)}")
        
        # Also log via logger for log files
        logger.info("Configuration validation completed successfully", extra=config_log_data)
        
    except Exception as e:
        error_msg = f"❌ Configuration validation failed: {str(e)}"
        print(error_msg)
        logger.error(error_msg)
        if not SETTINGS.dev:
            print("Exiting due to configuration validation failure")
            sys.exit(1)
        else:
            print("Continuing in development mode despite validation failure")


async def startup():
    # Validate and display configuration on startup
    await validate_and_display_config()
    
    aiohttp_client.start()
    sessionmanager.init(SETTINGS.database_url)
    await job_manager.init()

    # init predefined roles
    await init_predefined_roles()

    # init models
    await init_models()

    # init modules
    await init_modules()


async def shutdown():
    await sessionmanager.close()
    await aiohttp_client.stop()
    await job_manager.close()
    await websocket_manager.shutdown()
