# FulfillFlow Infra

Infraestrutura e operação do [FulfillFlow](https://github.com/campos-labs/fulfillflow)
no Azure Kubernetes Service (AKS), com imagens no Azure Container Registry (ACR).

**Estado: preparação local implementada; aceite do ambiente pendente.** Terraform,
manifests de exemplo, CI de validação e verificador funcional estão disponíveis.
Nenhum recurso Azure foi provisionado; ainda não há comando de implantação liberado.

## Objetivo

Preparar uma implantação funcional reproduzível, com réplicas fixas, persistência,
acesso restrito e verificação da conclusão do fluxo assíncrono. O trabalho para em
um marco de aceite operacional antes da decisão entre implantação/recuperação e
autoescalonamento. Essas alternativas estão separadas no plano e não autorizam
implementação antecipada.

## Referência da aplicação

| Campo | Referência |
| --- | --- |
| Repositório | `campos-labs/fulfillflow` |
| Tag | `v1.3.0-rc.1` |
| Commit | `9e3a135a00db218643633c7165d3106f0c8285e1` |
| Estado | Pré-release funcional; capacidade e estabilidade prolongada não avaliadas |
| Imagens no ACR | Publicação e digests ainda pendentes |

Core, Tracking e Notifications têm API e worker próprios. A base prevê seis
processos de aplicação, uma instância PostgreSQL com três bancos/roles e uma
instância RabbitMQ. Isso representa três serviços de aplicação e oito componentes
principais; Jobs, componentes do cluster e réplicas alteram a contagem de pods.
Notifications registra entrega simulada, sem envio externo.

Este repositório não é um fork da aplicação. Consome suas imagens e contratos
congelados; não copia código de negócio nem campanhas históricas.

## Documentação

| Documento | Responsabilidade |
| --- | --- |
| [DESIGN.md](DESIGN.md) | Arquitetura alvo da base operacional, fronteiras e contratos de implantação |
| [RELEASE_PLAN.md](RELEASE_PLAN.md) | Incrementos, validações, estado, pausa e alternativas ainda não aprovadas |

Antes de alterar arquivos, consultar as seções pertinentes do DESIGN e o
incremento autorizado no RELEASE_PLAN.

## Organização

| Caminho | Conteúdo |
| --- | --- |
| [infra/](infra/README.md) | Bootstrap e ambiente Terraform; planos com provider simulado nos testes |
| [k8s/](k8s/README.md) | Fundações, migrações e runtime; exemplo Kustomize sem agendamento |
| `.github/workflows/` | Validação Linux/Windows sem credenciais Azure |
| `scripts/` | Preparação de ferramentas, validação e verificador funcional |
| `config/` | Versões fixadas e ficha do ambiente ainda não aprovado |
| `tests/` | Contratos de rede/manifest e falhas do verificador/launchers |

## Validação local

Requer Python 3.12, uv 0.12.7 e PowerShell 7. Conferir seus caminhos completos antes
do uso. A preparação baixa Terraform 1.13.5 e kubectl 1.35.3 em `.tools/`, verifica
os hashes fixados e não altera o PATH nem ferramentas da aplicação. O primeiro
uso também baixa dependências, provider e schemas; não consulta Azure ou cluster.

Na raiz do repositório, com `uv` e PowerShell verificados:

```powershell
uv sync --frozen
uv run --frozen python scripts/setup_validation_tools.py
$env:PWSH_PATH = (Get-Command pwsh -ErrorAction Stop).Source
uv run --frozen python -m unittest discover -s tests -v
uv run --frozen ruff check scripts tests k8s/prepare_rabbitmq_definitions.py
uv run --frozen ruff format --check scripts tests k8s/prepare_rabbitmq_definitions.py
uv run --frozen python scripts/validate.py --output artifacts/validation-local-01
```

Cada comando deve terminar com saída zero antes do seguinte. O destino da validação
deve ser novo; não há sobrescrita ou retry. Para execução bloqueante a partir de
outro diretório, `scripts/Invoke-Validation.ps1` recebe `-Python` com o caminho
completo do Python da `.venv` e `-OutputDirectory` com um destino novo. Os parâmetros
opcionais `-Kubectl` e `-Terraform` também recebem caminhos completos.

O verificador `scripts/verify_flow.py` está preparado, mas **não foi executado contra
implantação**. Quando houver ambiente autorizado, criará dados sintéticos, observará
Tracking/Order e Notifications separadamente e verificará uma duplicata intencional.
Não é gerador de carga nem teste de capacidade; exige workers, migrações e segredos
da implantação. Sua evidência identifica a referência esperada, sem atestar por si
só qual imagem está em execução.

Schemas Kubernetes são os arquivos estritos 1.35.0 do projeto comunitário
`yannh/kubernetes-json-schema`, fixados por commit. Essa validação e os planos
Terraform com mocks não comprovam disponibilidade da versão no AKS, permissões,
quotas, custo, pull ou funcionamento dos volumes.

## Limites da primeira entrega

- AKS e ACR; nenhuma plataforma alternativa nesta etapa.
- Réplicas fixas, sem HPA/KEDA, Argo CD ou rollback automatizado.
- PostgreSQL e RabbitMQ persistentes com uma instância cada, sem promessa de HA.
- Acesso restrito; a aplicação não fornece autenticação de usuários.
- Aceitação HTTP 202, pod pronto ou fila vazia não comprovam conclusão de negócio.
- Verificações funcionais delimitadas; campanhas extensas continuam fora do escopo.

Próximo passo: concluir a ficha [config/environment.json](config/environment.json)
por consultas de leitura e revisão de custo/acesso, conforme
[RELEASE_PLAN.md](RELEASE_PLAN.md). Nenhum saldo ou benefício presumido autoriza gasto.
