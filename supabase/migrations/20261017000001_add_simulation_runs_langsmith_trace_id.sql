-- Correlación simulation_runs <-> LangSmith (#343): id de la traza raíz `simulation_run`.
-- Nullable: las corridas anteriores no tienen traza. Sin índice (se busca por run, no por traza).
ALTER TABLE simulation_runs ADD COLUMN IF NOT EXISTS langsmith_trace_id UUID;
