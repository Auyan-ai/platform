-- Bloque 1.10 — sistema de onboarding productizado (Fase 1)
-- Semilla para futuro tier trial / self-serve. Hoy solo la columna;
-- el flujo trial se diseña en Bloque 2+ (ver docs/onboarding-system-plan.md §7).

begin;

alter table tenants
  add column plan_tier text not null default 'founding'
    check (plan_tier in ('founding', 'standard', 'trial'));

commit;
