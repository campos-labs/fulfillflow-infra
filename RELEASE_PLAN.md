# FulfillFlow Infra — Estado de entrega e evolução

## 1. Estado atual

**Exploração de observabilidade encerrada no escopo executado**, na branch
`feature/v1.2-observability`, a partir de `v1.1.0-rc.1` (`92089b8`). O
[relatório técnico](docs/OBSERVABILITY_EVALUATION.md) consolida correlação dos workers,
captura HTTP saudável e sequência controlada 200 → 503 → 200, com limites explícitos.
Dois pacotes e diagramas reproduzíveis permitem examinar os resultados offline.
Não há nova carga necessária para conferir os casos. **v1.2 ainda sem tag, release
ou merge**; a próxima decisão é revisar a consolidação antes de publicar uma candidata.

| Referência | Entrega |
| --- | --- |
| [v1.0.0](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.0.0) | Recuperação em Kind; [relatório](docs/OPERATIONAL_EVALUATION.md) e dois pacotes preservados |
| [v1.1.0-rc.1](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.1.0-rc.1) | Comparação fixa/adaptativa concluída, integrada à main; [relatório](docs/SCALING_EVALUATION.md), figuras e três pacotes |
| v1.2 em revisão | Diagnóstico complementar, [relatório](docs/OBSERVABILITY_EVALUATION.md), [dois pacotes](docs/evidence/observability/README.md) e executores versionados |
| Azure | Referências Terraform/AKS/ACR não implantadas; portabilidade opcional, sem resultado de nuvem |

A aplicação congelada `9e3a135` sustenta recuperação, capacidade e os casos de workers.
A fatia HTTP usa derivação própria `045e1ca`, com [runtime identificado](config/http-observability.json).
Não substitui a aplicação nem as evidências das versões anteriores.

## 2. Responsabilidades dos documentos

| Documento | Responsabilidade |
| --- | --- |
| README | Resultado resumido e navegação |
| DESIGN | Contratos, arquitetura e limites dos procedimentos |
| Relatórios em docs | Problema, método executado, resultados, interpretação e fontes |
| Índices de evidências | Pacotes, manifestos, disponibilidade e reprodução offline |
| Guia Kubernetes / Terraform | Preparação, comandos e operação |
| Este plano | Estado da entrega, decisões pendentes e preservação |

## 3. Fechamento e verificação

A consolidação usa registros existentes; não modifica resultados nem reabre ensaios.
O [reprodutor](docs/evidence/observability/reproduce.py) verifica os casos, hashes,
conteúdo dos ZIPs e geração dos diagramas. Os originais selecionados continuam
legíveis no GitHub. A CI confere o pacote offline além das validações existentes;
não inicia o Kind ou a aplicação. Captura diagnóstica não equivale a custo medido.

Antes de eventual publicação: revisar texto, figuras e CI da referência final.
A candidata pode usar `v1.2.0-rc.1`; a tag identificará a consolidação, enquanto os
SHAs executados permanecem nos protocolos. Anexos devem ser cópias exatas dos ZIPs
versionados. Não mover tags ou substituir pacotes de releases anteriores.

<a id="3-extensões-possíveis"></a>
<a id="4-exploração-de-observabilidade"></a>
<a id="4-continuidade-condicionada"></a>

## 4. Continuidade condicionada

As [lacunas e alternativas](docs/OBSERVABILITY_EVALUATION.md#6-interpretação-e-caminhos-de-continuidade)
concentram o que justificaria métricas, instrumentação durável, segurança ou service
mesh. Não são entregas prometidas nem requisitos da v1.2. Não ampliar tracing,
refatorar aplicação ou abrir outra campanha automaticamente.

AKS permanece complemento opcional de portabilidade e funcionamento selecionado;
ACR depende da implantação escolhida. Os resultados quantitativos locais não se
transferem à nuvem. As consultas anteriores não estabeleceram configuração Azure
provisionável. Antes de apply, conferir acesso, região, quotas, restrições de SKU,
capacidade, orçamento e encerramento no [guia Terraform](infra/README.md).
Uma comparação correspondente exigiria protocolo próprio; mudar ambiente e
instrumentação juntos não isola o efeito de nenhum deles.

## 5. Preservação e histórico

O [histórico até a consolidação de observabilidade](https://github.com/campos-labs/fulfillflow-infra/blob/f6aafa0/RELEASE_PLAN.md)
e o [histórico de capacidade](https://github.com/campos-labs/fulfillflow-infra/blob/58f4483e0fdb2e5273b9b533d9173de494818a3c/RELEASE_PLAN.md)
preservam protocolos, emendas, correções, pausas e decisões. Resultados desfavoráveis,
claims e pastas originais permanecem intactos. IDs de tentativas e nomes históricos
de scripts existem para rastreabilidade; não são etapas pendentes na narrativa.

Os pacotes permitem conferir evidências, não garantem recriação de hardware/runtime,
backup independente ou reprodução externa das medições. Séries não selecionadas e
configurações privadas continuam locais. Scripts operacionais permanecem no Git.

Qualquer execução futura usa destino novo, volume e tempo previamente delimitados,
sem repetir até passar. O [guia](k8s/README.md#diagnóstico-http-com-tracing) preserva
as guardas e a regra de preparação do host. Alterações de contrato, desenho, custo
externo ou risco operacional exigem decisão própria.

Versões seguem capacidades compatíveis em MINOR, correções compatíveis em PATCH,
mudanças incompatíveis em MAJOR e candidatas `-rc.N`. Não reservar uma versão para
cada ferramenta ou ambiente.
