# ADR 0003 — Disponibilidad temporal y ciclos inmutables históricamente

Estado: aceptada.

## Contexto

Un timestamp del hecho no demuestra que la información fuera conocida. Una reprogramación tampoco convierte en válidas para el nuevo partido las predicciones del ciclo anterior.

## Decisión

Usar `as_of(decision_time)` y exigir `available_at <= decision_time`; distinguir OBSERVED/ESTIMATED y registrar versiones de cada input. RAW es inmutable. Conservar la identidad lógica `event` separada de `event_cycle`; un aplazamiento crea otro ciclo sin trasladar análisis/apuestas.

## Consecuencias

Los backtests reportan calidad de reconstrucción y no mezclan versiones futuras. Las liquidaciones verifican el ciclo. Una previsión puede referirse a una hora futura si ya estaba disponible; no se confunde `occurred_at` con disponibilidad.
