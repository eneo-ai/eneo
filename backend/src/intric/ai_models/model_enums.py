from enum import Enum


class ModelOrg(str, Enum):
    OPENAI = "OpenAI"
    META = "Meta"
    MICROSOFT = "Microsoft"
    ANTHROPIC = "Anthropic"
    MISTRAL = "Mistral"
    KBLAB = "KBLab"
    GOOGLE = "Google"
    BERGET = "Berget"
