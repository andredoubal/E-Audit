from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EAUDIT_", extra="ignore")

    database_url: str = "postgresql+psycopg2://eaudit:eaudit@localhost:5433/eaudit"
    cors_origins: str = "http://localhost:5173"
    # AI layer (Phase 2). Model/provider/endpoint are pure config — swap any of them here,
    # never in application code. `llm_model` is a LiteLLM provider-prefixed string
    # ("anthropic/claude-opus-5", "openai/gpt-4o", "ollama/llama3", ...).
    llm_model: str = "anthropic/claude-opus-5"   # EAUDIT_LLM_MODEL
    llm_disabled: bool = False              # EAUDIT_LLM_DISABLED
    allow_hosted_egress: bool = False       # EAUDIT_ALLOW_HOSTED_EGRESS (real-data escape hatch)
    data_is_synthetic: bool = True          # EAUDIT_DATA_IS_SYNTHETIC
    llm_base_url: str | None = None         # prod: in-VPC gateway (the ONLY swap point)
    embedding_model: str | None = None      # EAUDIT_EMBEDDING_MODEL — reserved for a future
        # embedding-based retrieval feature. No caller exists today: precedent/index.py is
        # deterministic structured-field scoring, not vector search. Present so an embedding
        # model can be configured independently of the generation model without restructuring
        # anything, once a real retrieval feature needs one.

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
