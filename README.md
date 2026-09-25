# FulfillFlow Infra

Infraestrutura e operação do [FulfillFlow](https://github.com/campos-labs/fulfillflow)
em Kubernetes, com laboratório Kind e configuração de referência para AKS/ACR.

**Estado: A1 e A2 concluídos em Kind; comparação de 20 tentativas conferida.** O laboratório
está parado, com dados e evidências preservados. Escopo, resultados e os dois
incrementos de entrega estão no [RELEASE_PLAN](RELEASE_PLAN.md).

## Objetivo

Implantar a aplicação congelada com réplicas fixas e verificar a conclusão do fluxo
assíncrono. A1 detecta e registra; A2 acrescenta restauração automatizada delimitada
e comparação com acionamento explícito, usando a mesma verificação. Kind foi o
ambiente da comparação; AKS/ACR e autoescalonamento são extensões opcionais.

## Referência da aplicação

| Campo | Referência |
| --- | --- |
| Repositório | `campos-labs/fulfillflow` |
| Tag | `v1.3.0-rc.1` |
| Commit | `9e3a135a00db218643633c7165d3106f0c8285e1` |
| Estado | Pré-release funcional; capacidade e estabilidade prolongada não avaliadas |
| Imagens no ACR | Somente na extensão Azure; publicação pendente e dispensável no A2 |

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

- Kind como ambiente principal; verificações AKS/ACR pendentes e fora da entrega A2.
- Réplicas fixas, sem HPA/KEDA ou Argo CD. A restauração automática A2 foi verificada em pilotos e comparação delimitada;
  os comandos A1 atuais continuam exigindo restauração explícita.
- PostgreSQL e RabbitMQ persistentes com uma instância cada, sem promessa de HA.
- Acesso restrito; a aplicação não fornece autenticação de usuários.
- Aceitação HTTP 202, pod pronto ou fila vazia não comprovam conclusão de negócio.
- Verificações funcionais delimitadas; campanhas extensas continuam fora do escopo.

A série A2-II 03 concluiu 20/20 tentativas, com cinco pares por cenário; as séries
parciais anteriores permanecem separadas. Resultados, proveniência e limitações
estão no [RELEASE_PLAN](RELEASE_PLAN.md#7-evolução-local--aceite-a1-e-entrega-a2).
As interfaces operacionais estão em [k8s/README.md](k8s/README.md).

O ciclo está pausado para reavaliação. Não há nova execução necessária para este
aceite; AKS/ACR e autoescalonamento dependem de decisão posterior. A comparação
local não comprova capacidade, estabilidade prolongada ou desempenho na nuvem.
