"""flood_validation — valida el producto de susceptibilidad de anegamiento
(meteorologia-flood-projections) contra una capa de "anegamiento real"
estimada con sensores remotos públicos (Sentinel-1, Sentinel-2, opcionalmente
Dynamic World).

Pipeline independiente: no modifica flood_monitor.py. Importa AOI/fecha de
ahí (mismo directorio, sin paquete) siguiendo la misma convención que
list_s1_items.py — la dirección del import es siempre
flood_validation -> flood_monitor, nunca al revés.

Ver flood-projections-feature-real-flood.V2.0.md (fuera de este repo) para
el plan completo. Fase 1 (fundamentos): AOI + ventana + config + manifiesto
de corrida, sin procesar rásters — solo `--dry-run`.
"""
