# FulfillFlow Infra

Implantação, recuperação e avaliação de capacidade do FulfillFlow em Kubernetes.
A [v1.0.0](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.0.0)
preserva a avaliação de recuperação em Kind. A
[v1.1.0-rc.1](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.1.0-rc.1)
acrescenta nove tentativas de capacidade fixa/adaptativa concluídas, relatório,
gráficos e evidências. É uma pré-release da infraestrutura.

| Avaliação | Resultado principal | Relatório |
| --- | --- | --- |
| Recuperação de configuração | Ambos os procedimentos restauraram e confirmaram o trabalho; o acionamento integrado dispensou a solicitação externa separada | [Avaliação operacional](docs/OPERATIONAL_EVALUATION.md) |
| Capacidade fixa/adaptativa | KEDA executou 1→2→1, sem vantagem de atendimento sobre uma réplica fixa neste perfil; duas réplicas reduziram a pendência local | [Avaliação de capacidade](docs/SCALING_EVALUATION.md) |

São duas avaliações experimentais complementares da mesma aplicação, com protocolos
e conjuntos separados. As campanhas estão encerradas; não exigem nova carga para
conferir os resultados. AKS/ACR permanecem referências opcionais não implantadas.

A branch `feature/v1.2-observability` inicia uma exploração delimitada de correlação
e diagnóstico. Seu [plano e critérios de continuidade](RELEASE_PLAN.md#4-exploração-de-observabilidade)
são separados das avaliações encerradas; ainda não há tracing integrado validado.

## Comece por aqui

| Necessidade | Documento |
| --- | --- |
| Entender método, resultados, limites e fontes | [Recuperação](docs/OPERATIONAL_EVALUATION.md) e [capacidade](docs/SCALING_EVALUATION.md) |
| Entender arquitetura e contratos | [DESIGN](DESIGN.md) |
| Conferir candidata e opções de continuidade | [RELEASE_PLAN](RELEASE_PLAN.md) e [nota da candidata](docs/releases/v1.1.0-rc.1.md) |
| Preparar ou operar o laboratório | [Guia Kubernetes](k8s/README.md) |
| Examinar a referência Azure | [Guia Terraform](infra/README.md) |

## Aplicação e limites operacionais

A referência é [FulfillFlow v1.3.0-rc.1](https://github.com/campos-labs/fulfillflow/tree/9e3a135a00db218643633c7165d3106f0c8285e1),
SHA `9e3a135a00db218643633c7165d3106f0c8285e1`. Core, Tracking e Notifications têm
API e worker próprios, com três bancos/roles PostgreSQL e RabbitMQ. Notifications
registra entrega simulada. Este repositório consome seus contratos, sem copiar
código de negócio ou comparar versões arquiteturais da aplicação.

A recuperação altera somente configuração elegível de `notifications-worker`;
não reverte dados nem rearma `BLOCKED`. A avaliação de capacidade varia réplicas
de `core-worker`, com nós fixos. Os mecanismos não foram exercitados conjuntamente.
HTTP 202, ACK, fila vazia e pod pronto não comprovam conclusão de negócio. Os
relatórios distinguem ação operacional, participação do worker e confirmação
observada, sem inferir HA, capacidade máxima, economia financeira ou desempenho AKS.

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

O destino deve ser novo. Para caminhos com espaços ou execução em outro diretório,
`scripts/Invoke-Validation.ps1` aceita `-Python` e `-OutputDirectory` absolutos;
`-Kubectl` e `-Terraform` são opcionais. Essa validação também roda na CI Linux/Windows:
testes, renderização, schemas e planos Terraform simulados. Não aplica recursos
nem executa as séries no Kind. Os comandos operacionais estão no guia Kubernetes;
as séries concluídas permanecem encerradas. A comparação de capacidade usa
configuração e destinos próprios; novas cargas dependem de decisão explícita.

## Organização e evidências

- `infra/` e `k8s/`: configuração e operação dos ambientes.
- `scripts/`, `tests/`, `config/`: executores, verificações e versões fixadas.
- `docs/evidence/operational-a/`: evidências preservadas da recuperação, com dois ZIPs.
- `docs/evidence/scaling/`: três ZIPs com as nove tentativas, índices e reprodução offline.
- `artifacts/`: originais e saídas locais ignorados pelo Git; não presumir disponibilidade por link.

Os [pacotes de capacidade](docs/evidence/scaling/archives) incluem a primeira
adaptativa originalmente fora da continuação. O [manifesto](docs/evidence/scaling/manifest.json)
separa originais, projeções e metadados selecionados. Configurações privadas,
credenciais, dumps e kubeconfigs não são distribuídos. Scripts dos experimentos
ficam versionados; os ZIPs permitem ler os resultados sem recriar o laboratório.

Conferência de integridade e estatísticas, sem Docker ou arquivos privados:

```powershell
python docs/evidence/scaling/reproduce.py
```

Para tabelas e figuras, consultar a [reprodução da leitura](docs/SCALING_EVALUATION.md#7-evidências-e-reprodução-da-leitura).
Os arquivos estão versionados, com pacotes também vinculados à pré-release.
Restauração de backup independente e reprodução das medições em outro computador
não foram verificadas.
