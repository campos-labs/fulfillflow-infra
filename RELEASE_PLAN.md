# FulfillFlow Infra — Estado de entrega e evolução

## 1. Estado atual

**Referência de entrega: `v1.3.0-rc.1` — portabilidade operacional para AKS.**
O [relatório](docs/AKS_PORTABILITY_EVALUATION.md), os
[dois pacotes](docs/evidence/aks-portability/README.md) e a
[nota da candidata](docs/releases/v1.3.0-rc.1.md) consolidam o aceite funcional,
persistência, rede e captura HTTP isolada. Execuções encerradas; não há ensaio
adicional previsto nesta entrega.

| Referência | Entrega |
| --- | --- |
| [v1.0.0](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.0.0) | Recuperação em Kind; [relatório](docs/OPERATIONAL_EVALUATION.md) |
| [v1.1.0-rc.1](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.1.0-rc.1) | Capacidade fixa/adaptativa; [relatório](docs/SCALING_EVALUATION.md), nove tentativas |
| [v1.2.0-rc.1](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.2.0-rc.1) | Correlação e diagnóstico; [relatório](docs/OBSERVABILITY_EVALUATION.md) |
| v1.3.0-rc.1 | [Portabilidade AKS](docs/AKS_PORTABILITY_EVALUATION.md), [dois pacotes](docs/evidence/aks-portability/README.md), diagrama e capturas reais |

## 2. Responsabilidades dos documentos

| Documento | Responsabilidade |
| --- | --- |
| README | Síntese e navegação |
| DESIGN | Arquitetura e contratos operacionais |
| Relatórios técnicos | Pergunta, método, resultados, interpretação e limites |
| Índices de evidências | Pacotes, hashes, seleções e conferência offline |
| Guias Kubernetes/Terraform | Configuração, comandos e operação |
| WINDOW_REVIEW | Protocolo aprovado da janela, não autorização reutilizável |
| Este plano | Estado e decisões de fechamento |

## 3. Fechamento

A candidata preserva resultados favoráveis, tentativas incompletas e limitações.
Novas execuções exigem protocolo e autorização próprios; a revisão offline usa
os registros versionados, sem provisionar recursos.

<a id="3-extensões-possíveis"></a>
<a id="4-exploração-de-observabilidade"></a>
<a id="4-continuidade-condicionada"></a>

## 4. Portabilidade para AKS

A descoberta, preparação e ajustes estão no
[histórico preservado](docs/history/aks-portability-preparation.md); a
[revisão da janela](infra/WINDOW_REVIEW.md) registra seu protocolo aprovado.
Autorização financeira permanece privada e não é reutilizável.

As [continuidades possíveis](docs/AKS_PORTABILITY_EVALUATION.md#6-limites-e-caminhos-de-continuidade)
dependem de pergunta e protocolo próprios. Nenhuma extensão técnica é requisito desta entrega.

## 5. Preservação

Os [pacotes](docs/evidence/aks-portability/README.md) permitem examinar os resultados
sem Azure; não são backups nem recriam a janela. Fontes privadas, states e
credenciais permanecem fora do Git. Os auxiliares são versionados; orquestradores
locais executados são identificados por hash, sem alegação de reexecução integral
por um único comando público. Não mover tags ou substituir anexos anteriores.

O histórico de [observabilidade](https://github.com/campos-labs/fulfillflow-infra/blob/f6aafa0/RELEASE_PLAN.md)
e de [capacidade](https://github.com/campos-labs/fulfillflow-infra/blob/58f4483e0fdb2e5273b9b533d9173de494818a3c/RELEASE_PLAN.md)
preserva decisões anteriores. Versões usam MINOR para capacidades compatíveis e
`-rc.N` para candidatas; não se reserva uma versão para cada ferramenta.
