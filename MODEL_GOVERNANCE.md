# Gobernanza de modelos y políticas

Foundation implementa soporte de versionado y controles; no entrena ni despliega un modelo deportivo. Las reglas funcionales vigentes están en [PROJECT_SPEC](docs/PROJECT_SPEC.md).

## Progresión y promoción

Primero se construyen baselines estadísticos y después Gradient Boosting. Redes tabulares, modelos temporales, embeddings, contexto/noticias y consenso solo se incorporan cuando demuestren mejora fuera de muestra frente a los baselines disponibles y al mercado sin vig.

La prioridad de evaluación es log-loss, calibración, CLV y ROI. Brier y errores de distribución/valor complementan la evaluación. ROI no es criterio único de selección: puede mejorar retrospectivamente por azar o por filtros diseñados después de ver los resultados.

Los modelos/políticas se evalúan por liga, mercado y segmentos pertinentes sin ocultar intentos fallidos. Un modelo estadístico puede superar a una red; la complejidad no implica promoción.

## Registry y track record

Una versión conserva artefacto/hash, SHA, familia, versión de features, fecha y métricas. Estados: `TRAINING`, `CANDIDATE`, `VALIDATED`, `PRODUCTION`, `DEGRADED`, `NO_VALIDATED`, `RETIRED`.

El deployment define `[valid_from, valid_to)` y el comienzo del track record prospectivo. La evaluación histórica reconstruida de una nueva versión se identifica como backtest; no se presenta como si esa versión hubiera tomado decisiones live antes de su despliegue. Las promociones y retiros deben conservar su historial.

Antes de una promoción operativa deberán existir un dataset manifest point-in-time, resultados fuera de muestra, calibración, comparación con baselines y evidencia de acceso autorizado al artefacto. Foundation no convierte una etiqueta `VALIDATED` en evidencia estadística de calidad.

## Ventanas e intentos

Ventanas: `TRAIN`, `DEVELOPMENT`, `HOLDOUT`, `PROSPECTIVE`. Los experimentos conservan número de intento, hash de configuración, hash del dataset, ventana de validación, SHA, resultados y pruebas de significancia cuando correspondan. Los backtests walk-forward respetan cronología y reportan proporción OBSERVED/ESTIMATED.

El holdout final bloqueado no puede consultarse mediante evaluación normal ni desbloquearse por el worker público. Su futura liberación será una acción manual explícita, privilegiada y auditada. Una ventana ya usada para tomar decisiones de diseño deja de ser un holdout intacto; no se vuelve a etiquetar como prueba inédita. La validación prospectiva oficial mantiene una importancia central.

## Probabilidad y selección simulada

La calidad probabilística y la selección de apuestas son evaluaciones distintas. El lado favorecido maximiza la probabilidad del modelo; el lado con value tiene edge positivo frente al benchmark sin vig. El edge es una diferencia de probabilidades y no reemplaza el cálculo del retorno esperado al precio real/simulado disponible.

`paper_all_v1` y `paper_recommended_v1` usarán una unidad fija y el máximo edge positivo. La segunda exige superar NO BET. Esta comparación permite evaluar si el filtro añade valor sin esconder el rendimiento del conjunto de probabilidades.

**Las políticas no están activadas al iniciar Foundation.** Quedó pendiente decidir Betano frente a mejor cuota como fuente de precio. Los thresholds de `no_bet_policy_v1` tampoco fueron acordados. Los borradores no cuentan como políticas en producción y no se utilizan para atribuir track record oficial.

## Configuración y vigencia

Los motivos NO BET son EDGE_INSUFFICIENT, DATA_QUALITY_LOW, MODEL_UNVALIDATED, OOD_HIGH, ENSEMBLE_UNSTABLE, ODDS_STALE y CRITICAL_CONTEXT_MISSING. Sus thresholds deben concentrarse en configuración versionada y los resultados deben registrar todos los motivos activados.

Una vez activada una configuración, no se modifica retroactivamente. Una nueva regla crea nueva versión con nueva vigencia y track record. Aplica también a mercados seleccionados, de-vig, selector de línea, calibración, confianza y filtros. Las versiones no pueden ajustarse usando resultados futuros de decisiones que pretenden evaluar.

La resolución del precio y los thresholds debe registrarse antes de la fase operativa de paper, junto con configuración/hash y fecha de entrada en vigor. No bloquea el desarrollo de Foundation.

## Métricas e integridad histórica

Conservar predicciones oficiales aunque sus cuotas o datos resulten stale; publicar diagnósticos y segmentos en vez de eliminar resultados desfavorables. Excluir solamente por reglas prospectivas y razones explícitas. La officialización usa el inicio real del ciclo y una regla aún por fijar antes de su uso operativo.

CLV requiere capturas de cierre definidas y disponibles; no existe todavía un cálculo de CLV operativo. Paper ROI requiere precio y liquidación coherentes con la política vigente. Los resultados de apuestas reales no intervienen en la publicación pública ni en la selección retrospectiva de políticas.
