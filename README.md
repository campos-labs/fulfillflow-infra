# FulfillFlow Infra

Infraestrutura e avaliações operacionais do FulfillFlow em Kubernetes.
Os relatórios separam resultado, método e limites; o
[plano de entrega](RELEASE_PLAN.md) identifica versões publicadas e pendências.

| Avaliação | Resultado principal | Relatório |
| --- | --- | --- |
| Recuperação de configuração | Ambos os procedimentos restauraram e confirmaram o trabalho; o acionamento integrado dispensou a solicitação externa separada | [Avaliação operacional](docs/OPERATIONAL_EVALUATION.md) |
| Capacidade fixa/adaptativa | KEDA executou 1→2→1, sem vantagem de atendimento sobre uma réplica fixa neste perfil; duas réplicas reduziram a pendência local | [Avaliação de capacidade](docs/SCALING_EVALUATION.md) |
| Correlação e diagnóstico | IDs reconstruíram o fluxo dos workers; OTel localizou uma falha HTTP controlada, com consulta 200 → 503 → 200 e sem medição de overhead | [Avaliação de observabilidade](docs/OBSERVABILITY_EVALUATION.md) |
| Portabilidade AKS | Fluxo funcional, persistência e rede verificados; quatro spans em consulta HTTP isolada; encerramento verificado | [Avaliação de portabilidade](docs/AKS_PORTABILITY_EVALUATION.md) |

As avaliações usam a mesma aplicação com protocolos distintos; não foram
executadas conjuntamente nem transferem resultados quantitativos do Kind para
AKS. A [v1.3.0-rc.1](docs/releases/v1.3.0-rc.1.md) consolida a portabilidade. O
[plano de entrega](RELEASE_PLAN.md) identifica as referências preservadas.

## Comece por aqui

| Necessidade | Documento |
| --- | --- |
| Entender método, resultados, limites e fontes | [Recuperação](docs/OPERATIONAL_EVALUATION.md), [capacidade](docs/SCALING_EVALUATION.md), [observabilidade](docs/OBSERVABILITY_EVALUATION.md) e [portabilidade](docs/AKS_PORTABILITY_EVALUATION.md) |
| Entender arquitetura e contratos | [DESIGN](DESIGN.md) |
| Conferir entregas, incremento ativo e pausas | [RELEASE_PLAN](RELEASE_PLAN.md) |
| Preparar ou operar o laboratório | [Guia Kubernetes](k8s/README.md) |
| Preparar a extensão Azure e seu encerramento | [Guia Terraform](infra/README.md) |

## Aplicação e limites operacionais

A referência funcional é [FulfillFlow v1.3.0-rc.1](https://github.com/campos-labs/fulfillflow/tree/9e3a135a00db218643633c7165d3106f0c8285e1)
(`9e3a135`); a fatia HTTP usa a derivação `045e1ca`, com
[runtime próprio](config/http-observability.json). A infraestrutura consome os
contratos da aplicação; arquitetura e guardas estão no [DESIGN](DESIGN.md).

HTTP 202, ACK, fila vazia e pod pronto não comprovam conclusão de negócio. As
avaliações delimitam o que foi confirmado e não demonstram prontidão para produção.

## Validação local

Requer Python 3.12, uv 0.12.7 e PowerShell 7. Conferir os executáveis antes do uso.
A preparação instala ferramentas verificadas em `.tools/`, sem alterar o PATH.
Na raiz do repositório, executar cada comando somente após saída zero do anterior:

```powershell
uv sync --frozen
uv run --frozen python scripts/setup_validation_tools.py
$env:PWSH_PATH = (Get-Command pwsh -ErrorAction Stop).Source
uv run --frozen python -m unittest discover -s tests -v
uv run --frozen ruff check scripts tests k8s/prepare_rabbitmq_definitions.py
uv run --frozen ruff format --check scripts tests k8s/prepare_rabbitmq_definitions.py
uv run --frozen python scripts/validate.py --output artifacts/validation-local-01
```

O destino deve ser novo. `scripts/Invoke-Validation.ps1` aceita caminhos absolutos
para Python, saída e ferramentas. A CI Linux/Windows verifica testes, renders,
schemas e planos Terraform simulados, sem aplicar recursos ou executar campanhas.
Procedimentos operacionais ficam nos guias; novas cargas exigem decisão própria.

## Organização e evidências

- `infra/` e `k8s/`: configuração e operação dos ambientes.
- `scripts/`, `tests/`, `config/`: executores, verificações e versões fixadas.
- `docs/evidence/operational-a/`: evidências preservadas da recuperação, com dois ZIPs.
- `docs/evidence/scaling/`: três ZIPs com as nove tentativas, índices e reprodução offline.
- `docs/evidence/observability/`: dois ZIPs e seleções legíveis, diagramas e conferência offline.
- `docs/evidence/aks-portability/`: dois ZIPs, seleções sanitizadas, capturas reais e verificação offline.
- `artifacts/`: originais e saídas locais ignorados pelo Git; não presumir disponibilidade por link.

Os índices de evidências descrevem seleção, hashes e reprodução. Credenciais,
states, dumps e kubeconfigs ficam fora dos pacotes. Executores históricos e
auxiliares Azure são versionados; os orquestradores locais da janela AKS estão
identificados por hash. Os ZIPs permitem revisar resultados, não recriam o ambiente.

Conferência offline, sem Docker ou arquivos privados:

```powershell
python docs/evidence/scaling/reproduce.py
uv run --frozen python docs/evidence/observability/reproduce.py
python docs/evidence/aks-portability/reproduce.py
```
