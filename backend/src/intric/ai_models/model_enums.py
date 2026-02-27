from enum import Enum


class ModelFamily(str, Enum):
    OPEN_AI = "openai"
    MISTRAL = "mistral"
    VLLM = "vllm"
    CLAUDE = "claude"
    AZURE = "azure"
    OVHCLOUD = "ovhcloud"
    E5 = "e5"


class ModelStability(str, Enum):
    STABLE = "stable"
    EXPERIMENTAL = "experimental"


class ModelHostingLocation(str, Enum):
    USA = "usa"
    EU = "eu"
    SWE = "swe"
    CHN = "chn"
    CAN = "can"
    GBR = "gbr"
    ISR = "isr"
    KOR = "kor"
    DEU = "deu"
    FRA = "fra"
    JPN = "jpn"


class ModelOrg(str, Enum):
    OPENAI = "OpenAI"
    META = "Meta"
    MICROSOFT = "Microsoft"
    ANTHROPIC = "Anthropic"
    MISTRAL = "Mistral"
    KBLAB = "KBLab"
    GOOGLE = "Google"
    BERGET = "Berget"
    GDM = "GDM"
