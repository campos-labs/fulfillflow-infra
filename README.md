# FulfillFlow Infra

Infraestrutura e operação do [FulfillFlow](https://github.com/campos-labs/fulfillflow)
no Azure Kubernetes Service (AKS), com imagens no Azure Container Registry (ACR).

**Estado: base documental.** Terraform, manifests, pipelines e verificações de
implantação ainda não foram implementados. Nenhum recurso Azure foi provisionado
por esta entrega; ainda não há comando de implantação liberado.

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
| [Contribuição da organização](https://github.com/campos-labs/.github/blob/main/CONTRIBUTING.md) | Governança e fluxo de revisão |
| [Segurança da organização](https://github.com/campos-labs/.github/blob/main/SECURITY.md) | Segredos, dados e relato de vulnerabilidades |

Antes de alterar arquivos, consultar as seções pertinentes do DESIGN e o
incremento autorizado no RELEASE_PLAN. Não há AGENTS.md ou CONTRIBUTING.md local.

## Organização prevista

Diretórios serão criados com suas implementações, sem arquivos vazios de reserva:

| Caminho | Conteúdo previsto |
| --- | --- |
| `infra/` | Bootstrap e infraestrutura Terraform |
| `k8s/` | Manifests e configuração por ambiente com Kustomize |
| `.github/workflows/` | Validação e implantação com GitHub Actions |
| `scripts/` | Operações repetíveis e verificador funcional |
| `experiments/` | Cenários somente após decisão e protocolo aprovados |

## Limites da primeira entrega

- AKS e ACR; nenhuma plataforma alternativa nesta etapa.
- Réplicas fixas, sem HPA/KEDA, Argo CD ou rollback automatizado.
- PostgreSQL e RabbitMQ persistentes com uma instância cada, sem promessa de HA.
- Acesso restrito; a aplicação não fornece autenticação de usuários.
- Aceitação HTTP 202, pod pronto ou fila vazia não comprovam conclusão de negócio.
- Verificações funcionais delimitadas; campanhas extensas continuam fora do escopo.

Próximo incremento: preparação local, CI de validação e definição do ambiente,
conforme [RELEASE_PLAN.md](RELEASE_PLAN.md). Região, dimensionamento, orçamento e
caminho de acesso precisam estar definidos antes de aplicar infraestrutura.
