from enum import Enum


class ModelFamily(str, Enum):
    OPEN_AI = "openai"
    AZURE = "azure"
    CLAUDE = "claude"
    MISTRAL = "mistral"


class ModelHostingLocation(str, Enum):
    USA = "usa"
    EU = "eu"
    SWE = "swe"


class ModelOrg(str, Enum):
    OPENAI = "OpenAI"
    META = "Meta"
    MICROSOFT = "Microsoft"
    ANTHROPIC = "Anthropic"
    MISTRAL = "Mistral"
    KBLAB = "KBLab"
    GOOGLE = "Google"
    BERGET = "Berget"


class ModelStability(str, Enum):
    STABLE = "stable"
    EXPERIMENTAL = "experimental"
