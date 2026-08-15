import json
from pathlib import Path
from openai import OpenAI
from app.core.config import get_settings
from app.schemas.contracts import CommitAnalysisResult, PortfolioPatch

PROMPT_DIR = Path(__file__).resolve().parents[3] / "prompts"

class LLMProvider:
    def analyze(self, context: dict) -> CommitAnalysisResult: raise NotImplementedError
    def patch(self, context: dict) -> PortfolioPatch: raise NotImplementedError

class OpenAICompatibleProvider(LLMProvider):
    def __init__(self):
        s = get_settings()
        if s.llm_provider == "groq":
            if not s.groq_api_key: raise RuntimeError("GROQ_API_KEY is required for AI analysis")
            self.client = OpenAI(api_key=s.groq_api_key, base_url=s.llm_base_url)
        else:
            if not s.openai_api_key: raise RuntimeError("OPENAI_API_KEY is required for AI analysis")
            self.client = OpenAI(api_key=s.openai_api_key, base_url=s.llm_base_url)
        self.model = s.llm_model
    def _ask(self, prompt: str, context: dict, schema: type):
        response = self.client.chat.completions.create(model=self.model, response_format={"type":"json_object"}, messages=[{"role":"system","content":prompt}, {"role":"user","content":json.dumps(context)}])
        return schema.model_validate_json(response.choices[0].message.content or "{}")
    def analyze(self, context: dict) -> CommitAnalysisResult:
        return self._ask((PROMPT_DIR / "commit_analysis.md").read_text(), context, CommitAnalysisResult)
    def patch(self, context: dict) -> PortfolioPatch:
        return self._ask((PROMPT_DIR / "portfolio_update.md").read_text(), context, PortfolioPatch)

def get_provider() -> LLMProvider:
    if get_settings().llm_provider not in ("openai", "groq"):
        raise RuntimeError("Only OpenAI-compatible providers are currently configured")
    return OpenAICompatibleProvider()