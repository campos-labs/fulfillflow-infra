# FulfillFlow Infra — Arquitetura da base operacional

## 1. Estado e autoridade

Este documento define a arquitetura e os contratos operacionais da entrega em
Kind: verificação de implantação, restauração delimitada e observação
posterior do trabalho aceito, entregues na v1.0.0. A seção 8.7 define o alvo de
autoescalonamento da v1.1, ainda não implementado nem verificado. AKS/ACR é uma
configuração de referência opcional, ainda não implantada; não é dependência local.

O [RELEASE_PLAN](RELEASE_PLAN.md) registra marcos e decisões pendentes. O relatório
[OPERATIONAL_EVALUATION](docs/OPERATIONAL_EVALUATION.md) reúne protocolos executados,
resultados, limites e evidências. Um contrato documentado não comprova execução;
um teste da aplicação não substitui sua verificação no ambiente operacional.

A referência é `campos-labs/fulfillflow`, `v1.3.0-rc.1`, commit
`9e3a135a00db218643633c7165d3106f0c8285e1`. Seus
[contratos](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/DESIGN.md),
[operação](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/README.md)
e [Compose](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/compose.yaml)
permanecem congelados. Não mover tags, alterar imagens históricas, reutilizar
bancos antigos ou apresentar resultados anteriores como aceite neste ambiente.

A aplicação conserva código, testes e construção das imagens; este repositório,
infraestrutura, configuração e verificação operacional. Incompatibilidade funcional
requer correção identificada na aplicação e nova referência aprovada, sem patches
silenciosos no build de infraestrutura.

## 2. Topologia aprovada

A base Kind da v1.0.0 usa um nó e uma réplica de cada processo. Na extensão da
seção 8.7, somente o worker selecionado poderá variar réplicas. A topologia de serviços
abaixo também orienta a extensão Azure, cujo dimensionamento exige decisão própria.

| Componente | Controlador | Responsabilidade |
| --- | --- | --- |
| Core API | Deployment + Service ClusterIP | Entrada HTTP, UI e consultas autenticadas aos serviços |
| Tracking API | Deployment + Service ClusterIP | Admissão durável, HMAC, inbox e timeline |
| Notifications API | Deployment + Service ClusterIP | Consultas de simulação e progresso |
| Core worker | Deployment | Comandos, efeitos e publicação de resultados/fatos |
| Tracking worker | Deployment | Publicação de comandos e finalização por resultado |
| Notifications worker | Deployment | Recepção durável e simulação idempotente |
| PostgreSQL | StatefulSet, uma réplica, PVC | Três bancos e roles independentes |
| RabbitMQ | StatefulSet, uma réplica, PVC | Transporte com vhost e permissões por fluxo |
| Migrações | Jobs por proprietário | Três históricos Alembic, antes do runtime |

Banco e broker únicos são pontos de falha compartilhados. Persistência e reinício
não constituem alta disponibilidade. Não ampliar a topologia sem requisito concreto.
Kustomize organiza os manifests de `k8s/`; Terraform descreve somente os recursos
Azure. Evitar dois controladores administrando o mesmo objeto.

## 3. Imagens e proveniência

Registrar origem, commit, target do Dockerfile, hash do lock, plataforma e identidade
efetiva de cada imagem. No Kind, carregar e conferir o ID da imagem local com
`imagePullPolicy: Never`; não são necessários registry ou credenciais Azure.
Na extensão Azure, ACR é o registry escolhido: usar `image@sha256:...`, sem `latest`
ou tags mutáveis. ID local Docker não é digest publicado no ACR.

APIs, workers e Jobs podem compartilhar a imagem `runtime` com comandos distintos.
Preservar Dockerfile, `uv.lock` e dependências da referência. Acesso ao checkout
privado deve ser mínimo e explícito. Uma reconstrução tem identidade própria e
exige smoke; não presumir identidade binária com uma imagem anterior.

PostgreSQL `18-trixie` e RabbitMQ `4.2.4-alpine` usam os digests do Compose congelado.
Conferir a plataforma dos nós; não atualizar dependências por conveniência. Se as
imagens forem importadas para ACR, registrar origem, destino e digest publicado.

## 4. Identidade, rede e segredos

Banco, AMQP, APIs internas e management do broker não recebem exposição pública.
Core usa `kubectl port-forward` autenticado ou caminho privado aprovado. A aplicação
não autentica usuários: segredos internos não tornam segura sua publicação na internet.

NetworkPolicies delimitam Core → APIs internas; Tracking API → Core API para as
consultas contratadas; cada processo → banco próprio; workers → broker; DNS e
acessos operacionais necessários. As roles PostgreSQL isolam os bancos. Aplicar
policies não comprova isolamento: verificar tráfego permitido e bloqueado.

Secrets são injetados por mecanismo protegido, sem valores em manifests, tfvars
versionados, argumentos registrados ou logs. Base64 não é criptografia. Usar
credenciais próprias, sem defaults do Compose. Proteger kubeconfigs, state, planos
e artefatos sensíveis; não criar fontes concorrentes de configuração.

A extensão Azure mantém estes contratos, detalhados em [infra/README](infra/README.md):

- identidades individuais com MFA; separar permissões ARM, Kubernetes, Storage e ACR;
- provisionamento separado do deploy, sem Owner da assinatura ou kubeconfig
  administrativo no pipeline;
- GitHub Actions por OIDC restrito ao repositório e branch/ambiente confiáveis;
- AKS com Entra e identidades gerenciadas; pull pela identidade kubelet, sem admin
  ACR; verificar modo RBAC/ABAC antes de atribuir validade a `AcrPull`;
- CNI Overlay/Cilium, ranges sem sobreposição e API Kubernetes pública restrita a
  IPv4 `/32`, conforme a configuração preparada. Essa conectividade ainda precisa
  ser aprovada e verificada com executor de origem estável. Não abrir a API para
  contornar conectividade nem presumir acesso privado pelo runner hospedado.

## 5. Estado, bootstrap e custo

Criar bancos, roles e permissões em recursos novos. Assets de bootstrap têm origem
registrada e credenciais próprias. Inicialização de volume vazio não atualiza
volumes existentes nem rotaciona senhas. PostgreSQL 18 conserva o layout do Compose;
RabbitMQ conserva nome do nó, hostname e caminho dos dados ao recriar pods.

PVCs têm capacidade e retenção explícitas. O Kind usa local-path; a referência AKS,
Azure Disk CSI. Exportar e conferir cópia independente antes de remover dados.
Existência de PVC ou backup não comprova restauração, que exige ensaio isolado.

Na extensão Azure, Terraform e provider têm versões fixadas e lock versionado.
Backend Blob usa Entra, locking e acesso restrito; seu bootstrap é separado do
ambiente removível. State e access keys não entram no Git. Backend e evidências
devem sobreviver ao encerramento dos recursos de execução.

Antes de `apply`, registrar assinatura, região, quotas, SKUs, discos, conectividade,
limite autorizado e estimativa de nós, armazenamento, registry, rede e logs, incluindo
encerramento e retenção. Budgets alertam, mas não suspendem consumo. Parar workloads
não implica custo zero. O procedimento de bootstrap e as guardas Terraform ficam
em [infra/README](infra/README.md).

## 6. Inicialização e ciclo de vida

| Processo | Comando da referência |
| --- | --- |
| Core API | `python -m fulfillflow` |
| Tracking API | `python -m fulfillflow.tracking` |
| Notifications API | `python -m fulfillflow.notifications` |
| Workers | `python -m fulfillflow.core.worker`, `python -m fulfillflow.tracking.worker`, `python -m fulfillflow.notifications.worker` |
| Migrações | `alembic -c alembic_core.ini upgrade head`, `alembic -c alembic_tracking.ini upgrade head`, `alembic -c alembic_notifications.ini upgrade head` |

Cada processo recebe `SERVICE_ROLE`, URL do banco e os segredos/URLs necessários
à sua responsabilidade e à validação de settings da referência. Essa validação
também exige os segredos HTTP do serviço nos workers, mesmo sem seu uso no fluxo
AMQP. A matriz em [k8s/README.md](k8s/README.md) registra esses requisitos, sem
copiar valores locais. As APIs internas escutam na porta 8000;
workers não expõem HTTP. Não copiar integralmente os blocos de ambiente do Compose.

Preparar bancos e broker; executar Jobs de migração por proprietário; verificar
heads `1301_core`, `1203_tracking` e `1301_notifications`; somente então liberar
runtime e smoke. Serializar operações sobre o mesmo schema. Não executar migration
concorrente no startup de cada pod nem tratar `depends_on` do Compose como recurso
Kubernetes. Jobs e operações têm prazo e diagnóstico de falha preservado.

Começar com dados novos, sintéticos e identificados. Não executar o corte de dados
v1.2 → v1.3 como parte deste deploy nem pressupor rollback de schema compatível.

APIs: `/health/live` observa o processo; `/health/ready` depende de banco e schema.
Configurar startup/liveness/readiness explicitamente nos manifests: o HEALTHCHECK
do Docker não é importado automaticamente pelo Kubernetes.

Workers: o verificador `python -m fulfillflow.messaging.health --service <serviço>`
usa arquivo local e também falha quando dependências ficam indisponíveis. Pode
informar prontidão, mas não deve ser copiado como liveness que provoque reinícios
durante uma pausa recuperável de banco/broker. Inicialmente, supervisionar saída
do processo e registrar prontidão; qualquer liveness adicional precisa distinguir
travamento local de dependência indisponível. Sem detector específico, registrar
a limitação de detecção de travamento, sem inventar garantia de recuperação.

Readiness falsa de um worker não interrompe seu consumo AMQP. Só o ciclo de vida
da aplicação controla a admissão de trabalho. Heartbeat, prontidão, backlog e
conclusão de negócio são observações distintas.

Propagar SIGTERM, preservar os 15 s de encerramento limitado da aplicação e reservar
pelo menos a margem de 20 s do Compose para os workers. Claims/leases pendentes
continuam duráveis. Validar UID, escrita temporária do heartbeat e permissões do
volume ao aplicar securityContext; não impor configuração que impeça o runtime.

## 7. Recursos e conclusão assíncrona

| Componente | Request CPU reduzido | Limite CPU | Request e limite de memória |
| --- | --- | --- | --- |
| Cada API e worker (seis processos) | 150m | 0,5 | 384 MiB |
| PostgreSQL | 750m | 2 | 2560 MiB |
| RabbitMQ | 250m | 0,5 | 512 MiB |
| Cada Job ativo | 250m | 0,5 | 384 MiB |

Com uma réplica de cada processo, o runtime soma requests de 1900m, limits de
5500m e memória de 5376 MiB, sem Jobs ou overhead. O perfil reduzido, usado no Kind,
altera somente requests de CPU;
preserva limits, memória, réplicas, imagens, pools, probes e prazos da base. São
reservas para fluxo funcional sequencial, não mínimos medidos nem capacidade
comprovada. Menor reserva pode aumentar latência sob contenção e não implica
redução proporcional de consumo ou cobrança. A base mantém requests iguais aos
limits; `k8s/overlays/reduced-functional` continua sendo exemplo AKS bloqueado.

Definir capacidade alocável para sistema, runtime, Jobs e manutenção antes de
provisionar. Não dimensionar apenas pela memória nem alegar equivalência com
campanhas anteriores. Rollout da aplicação usa `maxSurge: 0`, `maxUnavailable: 1`,
com possível indisponibilidade. A proposta AKS usa PVCs StandardSSD_LRS de 32 GiB e
16 GiB com `Retain`, sujeitos a custo e validação CSI. Seu pool prevê um nó extra
durante upgrade, sem mantê-lo normalmente alocado. Quota, custo temporário e rotação
do pool exigem revisão. Ausência de upgrades planejados não exclui reparos nem
permite operação permanente sem margem de manutenção; o perfil reduzido não
comprova suporte a pool AKS de nó único.

Preservar pools API 2/0 e worker 3/0, prefetch 8, lotes 20, polling 500 ms, lease
30 s e confirm timeout 5 s. Pools crescem com réplicas; banco e broker também
limitam a operação.

ACK confirma persistência em inbox técnica, não conclusão. O backlog pode ocupar
outboxes, inboxes técnicas ou eventos de negócio. Contar etapas separadamente e
eventos únicos pela identidade correta, sem somar cópias técnicas. Fila vazia,
HTTP 202 e pod pronto não bastam como aceite.

Observar oferta, aceitação, conclusão Tracking/Order, Notifications, pendências e
prazo separadamente. Trabalho retomável dispensa reenvio do webhook; `BLOCKED`
exige rearme auditável pelo proprietário. `SIMULATED` não é entrega externa.

## 8. Implantação e evidências operacionais

GitHub Actions valida mudanças. A operação local usa Python 3.12 para orquestração
e evidências, PowerShell 7 como entrada e kubectl/Kustomize para workloads, com as
versões fixadas no repositório. Terraform permanece restrito à infraestrutura Azure.
Implantação é acionada explicitamente e tem concorrência limitada por ambiente.
Acesso Azure por OIDC ocorre somente em jobs confiáveis. Execuções não confiáveis
não recebem credenciais nem executam apply.
A implantação exige autorização do ambiente de destino; CI de validação não
constitui autorização para provisionamento nem comprovação de execução operacional.

Verificação funcional usa fluxo público, IDs exclusivos, HMAC e polling limitado.
Não reenviar automaticamente um evento para transformar timeout em sucesso.
Falha de consulta não apaga aceitação; timeout de observação não prova perda.
Diagnóstico complementar usa CLIs proprietárias e leitura controlada, sem acesso
SQL cruzado de runtime ou alteração manual de estados.

Preservar SHA da aplicação e infraestrutura, digests, configuração sanitizada,
schemas, recursos efetivos, horários UTC, IDs de execução/evento e resultados.
Coletar logs controlados e eventos Kubernetes suficientes para distinguir falha
de implantação, dependência e negócio. Nenhum body, segredo ou kubeconfig em logs.
Opções `METRICS_ENABLED`/`OTEL_ENABLED` não comprovam instrumentação implementada;
Prometheus e tracing amplos permanecem fora do aceite inicial.

Relatórios e pacotes delimitados de evidências podem ser versionados após revisão
de conteúdo para compartilhamento, com inventário e hashes. Demais saídas ficam em
armazenamento controlado; um caminho ignorado pelo Git não equivale a backup.
Falha inesperada interrompe mutações e exige diagnóstico antes de nova tentativa em destino identificado; falhas deliberadas
seguem o encerramento definido na seção 8.4.
Retries ou reposição automática de tentativa falha são proibidos. As repetições
planejadas da comparação seguem o protocolo fixado; retries internos da aplicação e
reconciliação normal do Kubernetes permanecem distintos.

### 8.1. Verificação de uma revisão de runtime

Separar implantação, observação funcional e restauração. A verificação isolada
detecta e registra; seu veredito não dispara rollback, rearme, reenvio de evento
ou reparo. A restauração explícita e a conferência de funcionamento encerram a
tentativa. A política automática da seção 8.5 é uma operação distinta.

Cada tentativa altera um único Deployment, mantendo os demais workloads, réplicas,
recursos, probes e contratos da aplicação congelada. A mudança experimental não
inclui foundations, bootstrap, migrações, esquema, edição manual de dados ou rotação
de credenciais.
Configuração compartilhada não pode ser alterada como se afetasse só um consumidor;
usar referência específica do workload ou interromper diante de impacto mais amplo.
Fixar previamente revisão saudável restaurável, candidata, efeito esperado,
critérios e prazos. Não enfraquecer probes para favorecer a verificação funcional.

### 8.2. Identidade e portabilidade

Receber caminhos de executáveis, kubeconfig, contexto, namespace e destino de
evidências explicitamente; nunca depender de caminhos pessoais ou contexto corrente.
Recusar contexto divergente, exemplos AKS bloqueados e operações concorrentes no
mesmo ambiente. Separar configuração Kind/AKS sem criar um framework multiprovedor.
Criação inicial e retomada são operações distintas; não reinicializar volumes ou
secrets existentes para resolver falha de implantação.

Registrar identificador da tentativa, SHAs, imagem esperada e efetiva, hash do
manifest/configuração não sensível, revisão do Deployment, ReplicaSet e UIDs dos
pods exercitados. Referências de secrets são opacas; não exportar valores, hashes
de segredos ou kubeconfig. Imagem sozinha não identifica mudança de configuração.
Antes de atribuir sucesso à candidata, comprovar convergência da revisão e ausência
de execução concorrente da revisão anterior no workload-alvo. Se a candidata não
iniciar, registrar essa falha; sucesso por réplicas antigas não a valida.

### 8.3. Observação e julgamento

Registrar separadamente rollout, admissão, conclusão Tracking/Order e simulação
Notifications. Para eventos cujo resultado esperado inclui notificação, o fluxo
completo exige ambas as conclusões. Falha em Notifications não apaga sucesso de
Tracking. Preservar identidades e efeitos únicos pelos contratos existentes.

O resultado da implantação pode ser aprovado, reprovado ou inconclusivo; etapas
não executadas permanecem identificadas. Requisito não atendido no prazo só é
afirmado com observação suficiente: consulta indisponível ou resposta de admissão
perdida exige registrar a incerteza. Timeout não prova perda do evento.
Separar esse resultado do julgamento do cenário contra sua expectativa prévia:
uma falha esperada corretamente detectada aprova o teste, nunca a implantação.

Conferir o resultado com registros/consultas existentes além do booleano final do
verificador, sem construir outro sistema de observação. Preservar o diagnóstico
das probes e do rollout para avaliar informação adicional ou sobreposição.
Não exigir vantagem da verificação funcional nem mudar o cenário após observar
o resultado.

Usar relógio monotônico para durações e UTC para correlação; não subtrair relógios
monotônicos de processos distintos. Fixar prazos finitos por etapa e limite total
antes da tentativa. Durações observadas incluem polling e são distintas dos
timestamps de negócio. Timeouts não entram como durações de sucesso.
O registro mínimo relaciona tentativa, revisão, evento, oferta, aceitação conhecida
ou incerta, conclusões, falhas de consulta e pendência final. Não é carga comparativa.

### 8.4. Encerramento e preservação

Na primeira falha inesperada, parar mutações do cenário e preservar evidências;
uma falha deliberada prevista segue somente a observação e o encerramento definidos.
Na operação explícita, restauração é comando separado, com alvo e
configuração conhecidos, nunca efeito automático do veredito. A única exceção
automatizada é a política restrita da seção 8.5. Restaurar imagem e configuração
pertinente, não apenas a tag; registrar falha de restauração sem declarar sucesso
ou repetir automaticamente.

Depois da restauração, observar os eventos já aceitos durante o cenário sem
reentregá-los e identificar separadamente um evento novo de verificação. Este não
comprova recuperação das pendências anteriores. Trabalho BLOCKED exige o rearme
auditável previsto na aplicação, fora da restauração de configuração. Preservar lacunas,
finalizar o registro e parar os recursos dedicados conforme o procedimento local.

### 8.5. Restauração automatizada de runtime em Kind

A política reutiliza identidade, observação e restauração explícita, preservando
os contratos dos comandos. Comparar duas condições com o mesmo detector, aplicação,
cenário, prazos e verificação de resultado: restauração por
acionamento explícito e restauração acionada automaticamente. A diferença estudada
é o acionamento da recuperação; não atribuir ganho de detecção a essa automação.

O alvo único é `notifications-worker`. São permitidas a revisão saudável marcada
por tentativa e a falha de inicialização `DB_POOL_SIZE=0`.
Demais workloads, réplicas, imagens, probes, recursos e referências de secrets
permanecem estáveis. Não adicionar outra falha para procurar resultado favorável.

Na condição automática, restaurar uma única vez somente após reprovação definitiva
da candidata por falha de inicialização, com identidade e diagnóstico conferidos.
O nome do cenário ou o resultado esperado não bastam para disparar a política.
Aprovação não dispara restauração; timeout de observação, perda de conectividade,
resultado inconclusivo ou aceitação desconhecida não autorizam rollback automático.
Preservar o diagnóstico e interromper a sequência nessas situações.

Antes de aplicar a candidata, persistir intenção, identidade da tentativa e
referência saudável sanitizada e restaurável. Antes de restaurar, verificar
contexto, UID do namespace/Deployment, template candidato e referências estáveis;
proteger a operação contra concorrência e atualização de terceiro, com comparação
atômica no patch. Recusar configuração externa alterada ou restauração de outro
ambiente. Não usar `rollout undo` sem identificar a configuração correspondente.

Registrar intenção, envio e resultado da restauração em journal durável. Se o
executor interromper após envio incerto, a retomada explícita reconcilia o estado
observado antes de qualquer mutação. Se o template saudável já estiver aplicado,
apenas verificar. Não reaplicar cegamente, repetir a tentativa inteira ou declarar
sucesso por ausência de erro. Falha de restauração encerra a sequência e exige
diagnóstico; nenhuma cadeia automática de reparos é permitida.

Restauração de template não reverte banco, efeitos de negócio, migrations, volumes
ou secrets. Não fazer rearme de BLOCKED, reentrega de webhook ou edição de estados.
Só declarar recuperação funcional após comprovar identidade saudável e um evento
novo concluído em Tracking/Order e Notifications SIMULATED, com duplicata sem novo
efeito. Eventos previamente admitidos, quando existirem, são observados por leitura
e classificados separadamente. A comparação de acionamento e a observação do
trabalho previamente aceito seguem protocolos distintos; ver seção 8.6 e relatório.

Separar veredito da implantação candidata, resultado da política, recuperação e
julgamento do cenário. Uma restauração bem-sucedida não aprova a implantação
defeituosa. O cenário saudável mede também restaurações indevidas; seu retorno à
base é limpeza explícita fora do intervalo de avaliação da política.

Um observador comum registra aplicação da candidata, detecção, solicitação e envio
da restauração, convergência e conclusão de negócio, usando relógio monotônico
coerente por duração e UTC para correlação. Identificar ator humano/agente/script
do acionamento explícito; execução por agente não mede tempo de reação humana.
Não acrescentar espera artificial à condição explícita. Métricas, ordem e quantidade
de repetições executadas estão no [relatório operacional](docs/OPERATIONAL_EVALUATION.md).

### 8.6. Trabalho pendente e observação inconclusiva

Os cenários de pendência e inconclusão mantêm aplicação, workload, política e
guardas de identidade, com preparação e protocolo próprios. Não combinar falha de implantação
e falha de consulta na mesma tentativa; não juntar tempos ou denominadores aos da
comparação de acionamento.

**Pendência:** após confirmar a candidata `DB_POOL_SIZE=0`, admitir um evento novo,
confirmar Tracking/Order e observar publicação `SENT` com Notifications ainda
`NOT_RECEIVED`. Isso evidencia trabalho aguardando consumo; não demonstra que o
worker defeituoso recebeu/processou a mensagem nem persistência após ACK nele.
Somente então liberar o acionamento da restauração, com preparação comum às duas
condições. Registrar detecção, preparação, autorização e acionamento separadamente;
a duração desde a autorização não representa toda a indisponibilidade.
O acionamento explícito continua sendo comando separado por script, sem espera
artificial e sem representar reação humana. Revalidar identidade antes da mutação.

Observar o evento anterior exclusivamente por GET, sem reentrega ou rearme. A
infraestrutura restaura a configuração; a aplicação conclui o trabalho aguardando
consumo; o verificador confirma resultado e efeito único. O evento novo de smoke
da restauração continua separado e não substitui a verificação da pendência.

Desde antes da autorização, observar em paralelo o workload e o evento pendente.
Usar relógio monotônico do mesmo processo, UTC, início/fim das consultas e polling
declarado. O sinal de infraestrutura é a convergência da revisão saudável (réplicas,
geração observada, ausência da antiga e container pronto), com UID do pod; não
rotulá-lo como horário exato da transição Kubernetes `Ready`. Não somar atrasos de
consultas sequenciais como se fossem diferença intrínseca entre prontidão e negócio.
O consumo AMQP não é interrompido automaticamente por readiness falsa. Diferenças
observadas entre sinais não demonstram inadequação das probes.

**Inconclusão:** candidata saudável, evento com aceitação confirmada e uma falha
503 injetada no transporte do observador para consulta de Notifications. Identificar
a injeção explicitamente; serviços, armazenamento e Kubernetes são reais, mas ela
não equivale a uma queda real da API. A política existente deve recusar restauração.
Comprovar ausência de intenção/envio de patch de restauração e preservação de UID,
geração, template e referências de configuração; não confiar apenas no veredito.
Retirar a injeção e retomar GET sobre os mesmos IDs. Limpeza explícita da candidata
marcada ocorre depois dessas asserções, fora do intervalo avaliado.

Falha inesperada interrompe a sequência, preservando estado e evidências para
recuperação explícita. Nenhuma reposição automática ou alteração de critério após
observar resultados. Prazos, ordem e denominadores executados ficam no
[relatório operacional](docs/OPERATIONAL_EVALUATION.md).

### 8.7. Alvo de autoescalonamento em Kind

**Contrato da extensão v1.1; piloto integrado concluído, comparação formal pendente.** A base permanece
conforme as seções anteriores. A extensão varia apenas réplicas de um worker
selecionado, com nós e recursos do host fixos, aplicação congelada e demais
workloads estáveis. Calibração começa com uma e duas réplicas; a política mantém
mínimo de uma e máximo inicial de duas. Qualquer ampliação exige capacidade
verificada e configuração identificada antes de nova execução, fora desta calibração.

Criar ambiente de piloto dedicado, sem reutilizar bancos, volumes ou namespace
da avaliação encerrada; manter o laboratório histórico parado. Identificar cluster,
UIDs, imagens, configuração e recursos do host. Réplicas compartilham CPU, memória,
banco e broker; soma de requests não comprova folga, e mais pods não criam nós.
Preservar os parâmetros por réplica da seção 7. Contabilizar pools multiplicados,
limites PostgreSQL, controladores, coleta e gerador, inclusive quando externos ao cluster.

**Calibração preparatória.** O candidato inicial é `core-worker`: sua inbox durável
permite observar trabalho elegível após ACK. A réplica também executa recepção e
publicação; eventual efeito não será atribuído exclusivamente ao processamento SQL.
A consulta conta `PENDING`/`RETRY_WAIT` vencidos de `tracking.apply.v1`, em mensagens,
com retry futuro, `BLOCKED`, concluídos e idade apresentados separadamente.
A leitura pode incluir trabalho em transação ainda não confirmada: não mede apenas
mensagens ociosas. Sua utilidade ainda será avaliada. Role própria somente leitura,
quatro colunas autorizadas e timeout SQL limitam a coleta; erro não produz zero.

O instrumento usa Locust HttpSession em processo separado e agenda aberta limitada.
Registra para cada despacho o horário previsto, a tentativa, atraso e concorrência;
`client_concurrency_limit` e `scheduler_lag` podem ocorrer simultaneamente. A tolerância
de atraso permanece 250 ms. Não corrigir retrospectivamente uma oferta não realizada.

A coleta SQL/Kubernetes/kubelet tem execução independente da observação funcional,
com início/fim por amostra e atraso sobre a cadência nominal de cinco segundos.
Não instala Prometheus nesta etapa. Registra CPU acumulada e RSS por PID/criação
na árvore do instrumento e memória disponível do host. Processos muito curtos podem
escapar à amostragem; esses valores não são contabilização integral do host e não
devem ser somados aos recursos do nó, pois há sobreposição. Ausência/erro de coleta
interrompe o aceite; não vira zero. Tempos funcionais continuam limites superiores
observados, não horários exatos da confirmação de negócio.

Atribuir processamento pelos logs `core/process/DONE` da aplicação congelada,
correlacionados ao `request_id` do aceite, com UID e reinícios dos pods. Exigir
uma correspondência por aceite e inventário estável; lacuna não demonstra perda.
Dois pods Ready não provam participação de ambos. Não alterar a aplicação para
produzir essa atribuição. Consultas, recursos e logs têm limites de coleta e não
substituem a verificação funcional por evento.

**Caracterização posterior ao piloto.** Antes de uma comparação formal, a
condição fixa admite dois perfis limitados, com patamar de 30 s a 12 ou 16
mensagens/s entre 15 s a 2/s na entrada e na saída (420 ou 540 eventos).
O perfil histórico permanece inalterado. Exigir uma réplica, controle amostrado
do host e observador com reutilização terminal; preservar recursos e prazo.
A progressão entre perfis depende da revisão dos limites definidos previamente
no RELEASE_PLAN. Não extrapolar capacidade máxima nem transportar essas taxas
para KEDA automaticamente.

No diagnóstico de admissão a 12/s, permitir teto HTTP 16 em lugar de oito,
sem mudar agenda, observador ou workload. Identificar o instrumento e a mudança
no protocolo; oferta planejada igual não garante demanda efetiva igual.
Essa exceção não altera os padrões das calibrações ou do piloto KEDA.

**Controle e sinal.** KEDA é a opção preferencial e integra-se ao HPA; não criar
outro HPA independente sobre o mesmo alvo. Na condição fixa, o controlador não
pode disputar réplicas com o executor. Na adaptativa, manifests de rotina e scripts
não devem repor `replicas` durante a observação. Restauração automática da v1.0.0,
GitOps e mudanças de configuração não participam simultaneamente deste piloto.

Definir a métrica pelo trabalho elegível que o worker pode processar. Fila RabbitMQ,
inbox durável, trabalho em execução/lease e `BLOCKED` têm significados distintos;
mais réplicas não rearmam bloqueios. Confrontar o sinal com registros por evento e
estado persistido, sem somar cópias técnicas. Mínimo de uma réplica impede escala
a zero, mas não torna suficiente uma métrica que omite pendências após ACK.

KEDA pode consultar PostgreSQL ou uma métrica exportada. A escolha deve declarar
consulta, estados, idade, unidades, limiar, cadência, custo e comportamento diante
de dados ausentes/obsoletos. Acesso SQL operacional é somente leitura, com role
restrita ao banco e dados necessários, timeout e conexões limitadas; não usar
credenciais do worker nem contornar interfaces de negócio para escrever dados.
Credenciais, RBAC e acessos de rede dos componentes auxiliares devem ser explícitos.
Nenhum erro de consulta vira zero pendências. Documentar/testar o comportamento
real do controlador em falha de métrica, sem presumir que sempre conserva réplicas.

**Piloto KEDA delimitado.** KEDA 2.20.2, manifesto oficial core (sem webhook de
admissão adicional), hash e imagens amd64 fixados em `config/keda-pilot.json`.
Imagens por digest usam `IfNotPresent`: reaproveitar cache local sem exigir
consulta ao registry em cada retomada; download inicial continua necessário.
Instalação exclusiva em `fulfillflow-scale-01`; namespace `keda`, observação limitada
a `fulfillflow`, RBAC oficial do controlador no cluster dedicado. PostgreSQL usa
role própria somente leitura nas quatro colunas da inbox, timeout de 2 s e limite
de duas conexões. Segredo referenciado por TriggerAuthentication, sem modificar
credenciais da aplicação. Regra de rede permite PostgreSQL ao namespace KEDA;
o CNI local não comprova enforcement de NetworkPolicies.

Sinal: quantidade de `tracking.apply.v1` elegíveis (`PENDING`/`RETRY_WAIT` vencidos)
com pelo menos cinco segundos desde `created_at`. Alvo de uma mensagem envelhecida
por réplica, entre uma e duas réplicas. Cinco segundos é orçamento provisório da
etapa inicial dentro do prazo funcional de 60 s; não é limiar ótimo inferido dos
resultados nem mede exclusivamente espera ociosa. SQL retorna zero somente quando
não há linhas elegíveis; erro continua erro. Sem fallback ou escala a zero.
Polling KEDA 5 s, HPA conforme cadência efetiva registrada do cluster (padrão 15 s),
estabilização de subida 15 s e descida 300 s. `cooldownPeriod` não governa 2→1.
O perfil de carga permanece o da calibração 05. Não exigir aumento de réplicas.

O protocolo separa preparação/falha da métrica da oferta funcional. Injeta
`SELECT 1/0` somente na consulta do ScaledObject, sem alterar banco ou aplicação,
registra falha da API de métricas/condições do controlador e restaura a consulta
original. Não interpreta valores antigos do HPA como leitura válida. Após a carga,
observa por até 360 s sem novos eventos. Ausência de escala com leituras saudáveis
e ausência de critério nas amostras distingue-se de observação indisponível; não
prova o comportamento entre amostras. Logs por pod são preservados durante a execução
para acompanhar também pods removidos. Inventariar reinícios e lacunas de leitura.

No encerramento, exportar configuração/status, remover somente o ScaledObject
próprio e aguardar a exclusão do HPA antes de repor uma réplica e parar o nó.
Não apagar CRDs, credenciais, volumes nem históricos. A calibração 05 permanece
referência preparatória com hashes originais; o piloto não é repetição experimental.

**Entrada e resultado.** Locust é o gerador preferencial. Distinguir oferta
planejada/realizada, aceitação confirmada ou desconhecida, rejeição, conclusão e
pendência; observar conclusão independentemente do ritmo de admissão. Fixar taxa,
quantidade, distribuição de entidades/eventos e cadência de polling. Limitar também
a concorrência do gerador, declarando oferta não realizada quando esse limite
impedir a taxa prevista; não mascarar sua saturação. Preservar
HMAC e identidades; aceite desconhecido não autoriza reenvio automático.

Para eventos cujo resultado esperado é aplicação de transição, acompanhar
Tracking e estado esperado de Order e Notifications `SIMULATED` separadamente;
o conjunto de transições definido para concluir um pedido deve confirmar `FULFILLED`.
Não exigir pedido concluído após uma transição intermediária nem confundir resultado
terminal rejeitado com sucesso. Verificar efeitos únicos e IDs após aumento/redução,
sem webhook repetido ou rearme de `BLOCKED`. Não enfraquecer probes, SIGTERM ou leases.

O prazo funcional começa no aceite durável observado; registrar oferta e resposta
202 para declarar o limite dessa observação. Duração local usa relógio monotônico;
UTC e duração das consultas permitem alinhar séries sem presumir relógios idênticos.
Separar conclusão no prazo, conclusão tardia, pendência confirmada e observação
inconclusiva. Coortes devem ter a mesma oportunidade de observação, inclusive
aceites próximos ao fim da carga. A proporção de conclusão no prazo usa aceites
confirmados como denominador e identifica consultas inconclusivas; publicar também
oferta, recusas e aceites desconhecidos, sem descartá-los silenciosamente.
Prazo/observação posterior são finitos; timeout
não comprova perda. Drain mede pendências após cessar a oferta; não equivale a fila vazia.

**Coleta e interpretação.** Séries temporais são obrigatórias; Prometheus é a
opção preferencial, independente da fonte consultada por KEDA. Registrar cadência,
fonte, unidade e lacunas para demanda, backlog/idade por etapa, réplicas
solicitadas/disponíveis, eventos de escala e CPU/memória. Guardar IDs dos pods e
consumo do banco, broker e componentes auxiliares. Contadores do scaler não são
a única evidência de conclusão. Métricas agregadas não recebem event IDs como labels;
registros funcionais separados preservam identidade e resultado de cada evento.

Fixar versão/configuração, exportar dados legíveis por máquina e registrar overhead.
Comparações mantêm instrumentação equivalente. Falha na coleta tem classificação
própria, não vira sucesso nem falha de negócio. Menos pod-tempo não demonstra menor
custo Azure em nós fixos; escala observada não prova capacidade ou HA de produção.
Ganhos, equivalência e piora são admissíveis, sem requisito percentual favorável.

**Encerramento.** Definir antes do piloto limites, interrupção de oferta, coleta
final e propriedade da escala. Exportar evidências e classificar pendências antes
de suspender o controlador e parar os recursos dedicados; não deixar KEDA/HPA
recriando réplicas durante a pausa. Verificar o estado efetivo, preservar volumes
e não executar destruição como limpeza automática. Comandos só entram no guia
Kubernetes após implementação e validação; critérios da pausa ficam no RELEASE_PLAN.

## 9. Limites e evolução

O aceite deve identificar o ambiente efetivamente exercitado: Kind ou AKS.
O aceite local não encerra as verificações específicas da nuvem. Nenhum dos dois
marcos, isoladamente, demonstra HA, SLA de produção, capacidade, estabilidade
prolongada ou solução dos incidentes históricos da aplicação/ferramenta de medição.

A v1.0.0 entrega a recuperação das seções 8.5–8.6 e sua avaliação delimitada.
A seção 8.7 acrescenta o alvo do piloto de autoescalonamento, sem declarar capacidade
validada. Comparação formal, cluster autoscaler, Argo CD, canary/blue-green, novos
provedores de entrega e instrumentação ampla permanecem fora do próximo incremento.
O piloto KEDA foi exercitado no Kind, sem caracterizar capacidade ou substituir
a comparação formal. Implantação Azure permanece pendente. O
[RELEASE_PLAN](RELEASE_PLAN.md) delimita implementação, pausa e decisão posterior;
essas extensões não são requisitos para encerrar a avaliação da v1.0.0.

## 10. Ambiente local e avaliação em Kind

Kind é o ambiente da avaliação operacional. Ambas as condições usam o mesmo
ambiente; não misturar tempos locais com resultados futuros de AKS. A aplicação congelada e a topologia
de serviços não mudam. O overlay `k8s/overlays/kind-local`
usa um único nó, local-path com Retain,
credenciais próprias e imagem carregada localmente com `imagePullPolicy: Never`.
Imagem por tag local exige conferência do ID/digest carregado; não é digest ACR.
API Kubernetes e port-forward ficam em loopback e usam kubeconfig dedicado.

O perfil usa os requests reduzidos da seção 7, preservando limits e memória. Não há
equivalência de persistência, isolamento ou identidade com AKS. O Kindnet incluído na
versão fixada tem suporte a NetworkPolicies; comprovar isolamento exige testar tráfego
permitido e bloqueado, não apenas aplicar os objetos. ACR, Entra/OIDC, RBAC Azure, Azure
Disk e Cilium exigem verificação na nuvem. Recursos históricos nunca são
montados/reutilizados. Excluir o cluster pode perder os PVCs; exportação/backup precede
qualquer remoção. Versões e exceção temporária de cgroup ficam em
`config/kind-toolchain.json`.

## 11. Referências operacionais

- [Identidade e acesso no AKS](https://learn.microsoft.com/en-us/azure/aks/concepts-identity)
- [Integração AKS e ACR](https://learn.microsoft.com/en-us/azure/aks/cluster-container-registry-integration)
- [GitHub Actions e Azure por OIDC](https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect)
- [Backend Azure Blob do Terraform](https://developer.hashicorp.com/terraform/language/backend/azurerm)
- [Probes Kubernetes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
- [Budgets Azure](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets)
- [Controlador de NetworkPolicies no Kind 0.30.0](https://github.com/kubernetes-sigs/kind/blob/v0.30.0/images/kindnetd/cmd/kindnetd/main.go)

As referências abaixo descrevem capacidades das ferramentas; suas versões de
implantação serão selecionadas por compatibilidade e fixadas no incremento:

- [KEDA e HPA](https://keda.sh/docs/2.18/concepts/)
- [KEDA: consulta PostgreSQL](https://keda.sh/docs/2.18/scalers/postgresql/)
- [Prometheus: coleta e séries temporais](https://prometheus.io/docs/introduction/overview/)
- [Locust: extensão e eventos](https://docs.locust.io/en/stable/extending-locust.html)
