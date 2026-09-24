# FulfillFlow Infra

Infraestrutura e operação do [FulfillFlow](https://github.com/campos-labs/fulfillflow)
com alvo no Azure Kubernetes Service (AKS) e imagens no Azure Container Registry
(ACR), além de um ambiente Kind para preparação funcional local.

**Estado: aceite funcional local preservado; automação A1 em validação, piloto pendente.**
Os comandos de operação e verificação de uma revisão estão implementados e cobertos
por testes automatizados. O piloto em Kind ainda não foi executado: a porta do
cluster preservado foi reservada pelo Windows. O aceite anterior permanece preservado;
AKS/ACR e a escolha
do ambiente da comparação continuam pendentes. Escopo, evidências e limitações
estão no [RELEASE_PLAN](RELEASE_PLAN.md).

## Objetivo

Preparar uma implantação funcional reproduzível, com réplicas fixas, persistência,
acesso restrito e verificação da conclusão do fluxo assíncrono. A1 detectará e
registrará o resultado da implantação; o piloto termina com restauração manual
explícita. Recuperação automática e autoescalonamento permanecem alternativas
posteriores, sujeitas à decisão na pausa.

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
| [k8s/](k8s/README.md) | Operação por fases, contrato de secrets, overlay Kind e exemplos AKS bloqueados |
| `.github/workflows/` | Validação Linux/Windows sem credenciais Azure |
| `scripts/` | Preparação de ferramentas, validação e verificador funcional |
| `config/` | Versões fixadas, configuração Kind e ficha com campos Azure ainda pendentes |
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

O verificador `scripts/verify_flow.py` foi executado no Kind: cria dados sintéticos,
observa Tracking/Order e Notifications separadamente e verifica uma duplicata
intencional. Exige workers, migrações e segredo do carrier. Não é gerador de carga
nem atesta, isoladamente, a imagem executada. Identidade, resultados e limites do
ensaio estão no [RELEASE_PLAN](RELEASE_PLAN.md); operação e retomada do ambiente
preservado estão em [k8s/README.md](k8s/README.md).

Schemas Kubernetes são os arquivos estritos 1.35.0 do projeto comunitário
`yannh/kubernetes-json-schema`, fixados por commit. Essa validação e os planos
Terraform com mocks não comprovam disponibilidade da versão no AKS, permissões,
quotas, custo, pull ou funcionamento dos volumes.

## Limites do escopo atual

- AKS e ACR como alvo de nuvem; Kind como ambiente funcional local, sem equivalência com AKS.
- Réplicas fixas, sem HPA/KEDA, Argo CD ou rollback automatizado.
- PostgreSQL e RabbitMQ persistentes com uma instância cada, sem promessa de HA.
- Acesso restrito; a aplicação não fornece autenticação de usuários.
- Aceitação HTTP 202, pod pronto ou fila vazia não comprovam conclusão de negócio.
- Verificações funcionais delimitadas; campanhas extensas continuam fora do escopo.

Próximo passo: viabilizar o ambiente e executar o piloto da seção 7 do
[RELEASE_PLAN](RELEASE_PLAN.md#7-incremento-ativo--base-comum-e-a1). A interface
`scripts/Invoke-A1.ps1` e sua configuração estão descritas em [k8s/README.md](k8s/README.md#procedimento-a1).
Os testes automatizados não substituem o aceite integrado. O cluster anterior está
preservado e parado; nenhum piloto, campanha ou provisionamento Azure foi realizado
nesta etapa.
