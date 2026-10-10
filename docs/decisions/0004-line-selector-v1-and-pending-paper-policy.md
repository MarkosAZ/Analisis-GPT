# ADR 0004 — Selector v1 y políticas paper todavía no activadas

Estado: aceptada para Foundation; configuración de paper pendiente antes de activación.

## Contexto

Una descripción temprana del selector decía «solo HALF_LINE». La especificación final expresa la restricción funcional «sin push ni asiáticas» y conserva mercados ganador/BTTS/tres vías que no requieren línea numérica. El precio para paper se dejó explícitamente sin elegir entre Betano y mejor cuota; los thresholds NO BET tampoco fueron fijados.

## Decisión

Las líneas numéricas elegibles de v1 son half-point. INTEGER_PUSH y ASIAN_QUARTER se reconocen y almacenan, pero no se eligen. MONEYLINE/THREE_WAY sin push se representan como mercados sin línea y pueden ser elegibles sin clasificarlos falsamente como HALF_LINE. Las pruebas deben fijar esta interpretación; ampliar v1 a push requerirá otra versión.

Paper selecciona máximo edge positivo, no el lado más probable. Los borradores conservan `paper_all_v1` y `paper_recommended_v1`, pero no se activan hasta elegir precio y congelar la política/umbrales. No se fabrican números supuestamente acordados.

## Consecuencias

Se preservan los mercados sin línea y la prohibición final de push. La tasa NO_ELIGIBLE_LINE sigue siendo observable cuando haya ingestión. El desacuerdo pendiente de precio no bloquea Foundation ni crea un track record prematuro.
