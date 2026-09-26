# FulfillFlow Infra

[**v1.0.0 — operação e recuperação em Kind**](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.0.0).

Implantação e recuperação operacional do FulfillFlow em Kubernetes. A release
v1.0.0 usa Kind, uma aplicação congelada e réplicas fixas. Foram conferidas uma
comparação de 20 tentativas e uma avaliação complementar de nove tentativas,
tratadas separadamente. O último encerramento preservou dados e parou o laboratório.

**Próxima entrega: viabilidade de autoescalonamento em Kind, ainda não implementada.**
A branch `feature/v1.1-autoscaling-kind` parte da v1.0.0. O
[incremento planejado](RELEASE_PLAN.md#3-incremento-de-viabilidade-em-kind)
termina com piloto limitado e pausa para reavaliação, antes de uma comparação formal.
A configuração de referência AKS/ACR continua opcional e ainda não foi implantada.

## Comece por aqui

| Necessidade | Documento |
| --- | --- |
| Entender resultados, conclusões e suas fontes | [Avaliação operacional](docs/OPERATIONAL_EVALUATION.md) |
| Entender arquitetura e limites da automação | [DESIGN](DESIGN.md) |
| Consultar entregas, pendências e extensões possíveis | [RELEASE_PLAN](RELEASE_PLAN.md) |
| Preparar ou operar o laboratório | [Guia Kubernetes](k8s/README.md#caminho-kind-local) |
| Examinar a configuração Azure ainda não implantada | [Guia Terraform](infra/README.md) |

## Aplicação e mecanismo avaliado

A referência é [FulfillFlow v1.3.0-rc.1](https://github.com/campos-labs/fulfillflow/tree/9e3a135a00db218643633c7165d3106f0c8285e1),
commit `9e3a135a00db218643633c7165d3106f0c8285e1`. Core, Tracking e Notifications
possuem API e worker próprios, com três bancos/roles em PostgreSQL e RabbitMQ.
Notifications registra entrega simulada; não envia mensagens a provedores externos.
Este repositório consome a aplicação e seus contratos, sem copiar código de negócio.

A ferramenta verifica revisões e oferece restauração explícita. A política
automática confirma uma falha de inicialização do `notifications-worker`, confere
sua identidade e restaura uma configuração conhecida. A comparação mantém
aplicação, detector e verificador comuns às duas condições; o acionamento explícito
é realizado por script. Os complementos observam trabalho aguardando consumo e
abstenção diante de falha de consulta injetada. A política não reverte dados nem
rearma trabalho `BLOCKED`.

O [relatório](docs/OPERATIONAL_EVALUATION.md) distingue configuração restaurada,
convergência do workload e conclusão funcional. Aceitação HTTP 202, pod pronto ou
fila vazia não comprovam, isoladamente, conclusão de negócio. Os resultados não
estimam capacidade, estabilidade prolongada, alta disponibilidade ou desempenho no AKS.

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
as séries concluídas permanecem encerradas. O piloto de autoescalonamento terá
configuração e destinos próprios, após implementação e verificações pertinentes.

## Organização e evidências

- `infra/`: bootstrap e ambiente Terraform; requisitos de nuvem ainda pendentes.
- `k8s/`: manifests por fase, overlay Kind, exemplos AKS bloqueados e contratos de secrets.
- `scripts/`, `tests/`, `config/`: operação, verificações e versões fixadas.
- `docs/evidence/operational-a/`: seleção versionada de dados e projeções rastreáveis.
- `artifacts/`: saída local ignorada pelo Git; não presumir acesso por link ao repositório.

O [índice de evidências](docs/OPERATIONAL_EVALUATION.md#8-evidências-e-reprodução-da-leitura)
reúne a leitura guiada e os [dois ZIPs completos](docs/evidence/operational-a/archives)
dos conjuntos concluídos, com checksums. Pilotos e séries interrompidas permanecem
locais, com suas exclusões documentadas. A release também reúne os dois ZIPs e
checksums; restauração de backup independente não foi verificada.
