# FulfillFlow Infra — Arquitetura da base operacional

## 1. Estado e autoridade

Este documento define a base operacional e o contrato A2 de restauração
automatizada em Kind. A configuração AKS/ACR permanece como alvo de nuvem
opcional, fora da entrega A2; as diferenças locais estão na seção 10.
O estado de implementação e as verificações executadas pertencem ao
[RELEASE_PLAN.md](RELEASE_PLAN.md). Um requisito descrito aqui não comprova que o
recurso já exista ou que sua verificação tenha sido executada.

A aplicação de referência é `v1.3.0-rc.1`, commit
`9e3a135a00db218643633c7165d3106f0c8285e1`, de `campos-labs/fulfillflow`.
Seus [contratos](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/DESIGN.md),
[operação](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/README.md)
e [Compose](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/compose.yaml)
são referências congeladas. Não mover tags, alterar imagens históricas, restaurar
bancos antigos neste ambiente ou copiar seus resultados como aceite no AKS.

O repositório da aplicação conserva código, testes e construção das imagens.
Este repositório conserva infraestrutura, configuração de implantação e
verificação operacional. Incompatibilidade funcional comprovada requer correção
identificada na aplicação e nova referência aprovada; não usar patches silenciosos
no build de infraestrutura.

## 2. Topologia aprovada

A topologia de serviços abaixo é comum ao Kind e ao alvo Azure. A2 usa o ambiente
local da seção 10, com réplicas fixas. No alvo Azure, usar uma região, AKS com
capacidade de nós explícita e fixa, ACR privado e namespace dedicado. A primeira
implantação usa uma réplica de cada processo da aplicação. Contagens de nós e
SKUs dependem do dimensionamento e orçamento aprovados.

| Componente | Controlador previsto | Responsabilidade |
| --- | --- | --- |
| Core API | Deployment + Service ClusterIP | Entrada HTTP, UI e consultas autenticadas aos serviços |
| Tracking API | Deployment + Service ClusterIP | Admissão durável, HMAC, inbox e timeline |
| Notifications API | Deployment + Service ClusterIP | Consultas de simulação e progresso |
| Core worker | Deployment | Comandos, efeitos e publicação de resultados/fatos |
| Tracking worker | Deployment | Publicação de comandos e finalização por resultado |
| Notifications worker | Deployment | Recepção durável e simulação idempotente |
| PostgreSQL | StatefulSet, uma réplica, PVC | Três bancos e roles independentes |
| RabbitMQ | StatefulSet, uma réplica, PVC | Transporte com vhost e permissões por fluxo |
| Migrações | Jobs por proprietário | Aplicar os três históricos Alembic antes do runtime |

Banco e broker únicos são pontos de falha compartilhados. Persistência e reinício
não constituem alta disponibilidade. Não acrescentar gateway, serviço de domínio,
réplica ou operador apenas para aumentar a topologia.

Manifests são declarados em `k8s/`, com Kustomize para configuração por ambiente.
Terraform gerencia os recursos Azure; o fluxo de implantação gerencia os recursos
Kubernetes. Evitar dois controladores administrando o mesmo objeto.

## 3. Imagens e proveniência

Na extensão Azure deste projeto, ACR é o registry escolhido. Não é requisito do A2
local nem exigência universal do AKS. A implantação usa referências `image@sha256:...`,
sem `latest` ou dependência de tags mutáveis. Registrar para cada imagem: origem,
commit, target do Dockerfile, hash do lock, plataforma e digest de registry.
Um ID local Docker não é um digest publicado no ACR. No A2, carregar e conferir
as imagens locais é suficiente; não provisionar registry nem credenciais Azure.
A rastreabilidade deriva da referência congelada, identidade efetiva e configuração,
sem depender da presença de um serviço de nuvem.

APIs, workers e Jobs podem compartilhar a mesma imagem `runtime`, mudando comando
e configuração. Não exigir uma imagem diferente por processo. Preservar o
Dockerfile, `uv.lock` e dependências da referência. A construção/publicação pertence
ao fluxo de aplicação; acesso a um checkout privado deve ser mínimo e explícito.
Uma reconstrução tem identidade própria e exige smoke, sem alegar identidade
binária com as imagens locais previamente verificadas.

As imagens PostgreSQL `18-trixie` e RabbitMQ `4.2.4-alpine` têm digests no Compose
congelado. Fixar esses digests na implantação e, se importadas para ACR, registrar
origem/destino e resolver o digest publicado. Não atualizar dependências durante
a preparação por conveniência. Conferir a compatibilidade da plataforma de nós.

## 4. Identidade, rede e segredos

- Pessoas usam identidades individuais com MFA. O bootstrap fica com a
  administração atual; a entrada posterior da equipe não exige recriar recursos.
- Separar acesso Azure Resource Manager, autorização no Kubernetes, dados do
  Storage e acesso ao ACR. Contributor não concede automaticamente todos eles.
- Automação GitHub Actions usa OIDC com confiança restrita ao repositório e ao
  ambiente/branch autorizado, sem credencial humana ou segredo permanente de login.
- Separar permissões de provisionamento e implantação. Atribuições de roles ficam
  no bootstrap controlado; o deploy cotidiano não recebe Owner da assinatura.
- AKS usa identidades gerenciadas, incluindo pull do ACR pela identidade kubelet.
  Fixar o modo de permissões do ACR; `AcrPull` no modo RBAC e roles de repositório
  no modo ABAC não são intercambiáveis. Não habilitar usuário admin do ACR.
- Habilitar autenticação Entra e autorização delimitada no cluster. Não distribuir
  kubeconfig administrativo como credencial de pipeline.

Banco, AMQP, interfaces internas e management do broker não recebem exposição
pública. Core começa acessível por túnel autenticado (`kubectl port-forward`) ou
caminho privado aprovado. Não há autenticação de usuários na aplicação; não
publicar UI/APIs de negócio na internet apenas com os segredos internos.

Antes de criar AKS, definir se o endpoint Kubernetes é privado ou público com
restrição de origem, e como o executor chega a ele. Runner hospedado no GitHub
não tem acesso implícito a uma rede privada. Não abrir o cluster a toda a internet
para contornar conectividade. Registrar a escolha, o custo e suas limitações.

Usar NetworkPolicies com matriz de tráfego: Core → APIs internas; Tracking API →
Core API para consultas do contrato congelado; cada processo →
banco próprio; workers → broker; DNS e acessos operacionais estritamente necessários.
As roles PostgreSQL continuam sendo a autoridade para isolamento entre bancos.

A configuração Terraform usa Azure CNI Overlay com Cilium e propõe API Kubernetes
pública restrita a IPv4 individuais `/32`; não é escolha de conectividade já
aprovada. Confirmar ranges sem sobreposição, DNS e executor com origem estável
antes de criar o ambiente. O provider fixado não configura o modo RBAC/ABAC do
ACR: verificar o modo efetivo antes de conceder validade ao contrato de pull.

Secrets de runtime são injetados por mecanismo protegido definido antes do deploy;
nenhum valor real em manifests, tfvars versionados, argumentos registrados ou logs.
Kubernetes Secret em base64 não é criptografia. Segredos padrão do Compose são
exclusivos do ambiente local e não serão reutilizados. Proteger também state,
planos Terraform, kubeconfigs e artefatos que possam conter informações sensíveis.
A escolha entre injeção protegida no deploy e Key Vault deve ser registrada sem
introduzir uma segunda fonte de configuração concorrente.

## 5. Estado, bootstrap e custo

Usar Terraform com provider/CLI compatíveis e versões fixadas no incremento de
preparação; versionar `.terraform.lock.hcl`. Backend remoto Azure Blob com
autenticação Entra, locking e acesso restrito. Bootstrap do backend é explícito,
identificado e separado do ambiente removível. Não guardar state no Git nem
fornecer access keys no código. Backend e cópia das evidências devem sobreviver
ao encerramento dos recursos de execução.

PVCs usam classe de armazenamento suportada no AKS, capacidade explícita e
políticas de retenção documentadas. PostgreSQL 18 usa o layout de volume do
Compose congelado; não assumir caminhos de versões anteriores. RabbitMQ conserva
nome do nó, hostname estável e caminho dos dados ao recriar pods.

Criar bancos/roles e permissões em recursos novos. Scripts de bootstrap e
definitions do broker derivados da referência devem ter origem registrada e
credenciais substituídas; não copiar defaults locais. Inicialização de volume vazio
não é mecanismo de rotação de senha ou atualização de volume já existente.

Antes de `apply`, registrar assinatura, região, quotas, SKUs, discos, conectividade,
estimativa de custo, limite de gasto autorizado e procedimento de encerramento.
Incluir nós, armazenamento, registry, rede e retenção de logs. Budgets geram alertas,
não suspendem consumo automaticamente. Não prometer custo zero por parar workloads.

Exportar evidências e verificar a cópia independente antes de remoção de dados.
Restauração será ensaiada apenas em destino isolado, com registros próprios;
persistência de PVC e existência de backup não comprovam recuperação verificada.

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

| Referência funcional local | Limite CPU | Limite memória |
| --- | --- | --- |
| Cada API e cada worker (seis processos) | 0,5 | 384 MiB |
| PostgreSQL | 2 | 2560 MiB |
| RabbitMQ | 0,5 | 512 MiB |

Esses limites somam 5,5 CPUs e 5376 MiB, excluindo Jobs e overhead do cluster;
não são dimensionamento de nós nem capacidade comprovada. Definir requests,
limits, espaço para sistema/rollout/Jobs e número de nós antes do provisionamento.
Começar pelos limites funcionais da referência e registrar qualquer ajuste de
implantação antes do aceite. Não alegar equivalência com campanhas anteriores.

O exemplo inicial usa requests iguais aos limites da tabela, mais 0,5 CPU/384 MiB
por Job ativo; a capacidade alocável dos nós precisa comportar esses valores e
o sistema. Rollout da aplicação usa `maxSurge: 0`, `maxUnavailable: 1`, com possível
indisponibilidade. PVCs de 32 GiB e 16 GiB em StandardSSD_LRS, retenção `Retain`,
são proposta ainda sujeita a custo e validação CSI. Não dimensionar nós apenas pela
memória nem reduzir recursos para caber em crédito presumido. A proposta Terraform
configura um nó adicional durante upgrade; não mantém esse nó alocado normalmente.
Quota e custo temporários entram na revisão. Uma janela funcional sem upgrades
planejados não garante ausência de reparos nem autoriza operação permanente sem
margem de manutenção. Rotação do pool exige revisão explícita do plano Terraform.

O perfil separado `k8s/overlays/reduced-functional` reduz somente requests de CPU:
150m por API/worker, 750m para PostgreSQL, 250m para RabbitMQ e 250m por Job.
Mantém limits, memória, réplicas, imagens, pools, probes e prazos da base. Os valores
são candidatos para fluxo funcional sequencial, não mínimos medidos. Requests do
runtime somam 1900m; limits continuam em 5500m. Sob contenção, menor reserva de CPU
pode aumentar latência; não implica redução proporcional de consumo ou cobrança.
O perfil herda o bloqueio de agendamento do exemplo e ainda não autoriza deploy.
Compatibilidade do pool AKS, quotas, capacidade alocável, componentes de sistema
e política de upgrade devem ser resolvidas antes da implantação. A existência do
perfil não comprova suporte a um cluster de nó único. Estado e critérios de
avaliação estão no RELEASE_PLAN.

Manter os parâmetros iniciais da aplicação: pools API 2/0 e worker 3/0,
prefetch 8, lotes 20, polling 500 ms, lease 30 s e confirm timeout 5 s. A soma
dos pools cresce com réplicas; banco e broker também podem limitar a operação.

ACK significa persistência em inbox técnica, não conclusão. O backlog pode estar
em outboxes, inboxes técnicas ou eventos de negócio pendentes. Contar etapas
separadamente e eventos únicos pela identidade correta; não somar cópias técnicas.
Fila RabbitMQ vazia, HTTP 202 e pod pronto não bastam como aceite.

Observar separadamente oferta, aceitação, conclusão Tracking/Order, simulação
Notifications, pendências e prazo de observação. Eventos retomáveis recuperam-se
sem reenvio do webhook; `BLOCKED` exige rearme auditável pelo proprietário.
`SIMULATED` não significa entrega a um provedor externo.

## 8. Implantação e evidências operacionais

GitHub Actions valida mudanças. A operação local usa Python 3.12 para orquestração
e evidências, PowerShell 7 como entrada e kubectl/Kustomize para workloads, com as
versões fixadas no repositório. Terraform permanece restrito à infraestrutura Azure.
Implantação é acionada explicitamente e tem concorrência limitada por ambiente.
Acesso Azure por OIDC ocorre somente em jobs confiáveis. Execuções não confiáveis
não recebem credenciais nem executam apply.
A implantação exige autorização do ambiente de destino; CI de validação não
constitui autorização para provisionamento.

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

Relatórios pequenos e sanitizados podem ser versionados. Dados brutos ficam em
armazenamento controlado, com inventário, hashes e retenção definidos; um caminho
ignorado pelo Git não equivale a backup. Falha inesperada interrompe mutações e
exige diagnóstico antes de nova tentativa em destino identificado; falhas deliberadas
seguem o encerramento definido na seção 8.4.
Retries ou reposição automática de tentativa falha são proibidos. As repetições
planejadas de A2 seguem o protocolo fixado; retries internos da aplicação e
reconciliação normal do Kubernetes permanecem distintos.

### 8.1. A1 — Verificação de uma revisão de runtime

Separar implantação, observação funcional e restauração. A1 detecta e registra;
seu veredito nunca aciona rollback, rearme, reenvio de evento ou reparo automático.
O encerramento do piloto inclui restauração manual explícita e conferência do
funcionamento; não equivale a uma política de recuperação automática.

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
Não exigir vantagem de A1 nem mudar o cenário após observar o resultado.

Usar relógio monotônico para durações e UTC para correlação; não subtrair relógios
monotônicos de processos distintos. Fixar prazos finitos por etapa e limite total
antes da tentativa. Durações observadas incluem polling e são distintas dos
timestamps de negócio. Timeouts não entram como durações de sucesso.
O registro mínimo relaciona tentativa, revisão, evento, oferta, aceitação conhecida
ou incerta, conclusões, falhas de consulta e pendência final. Não é carga comparativa.

### 8.4. Encerramento e preservação

Na primeira falha inesperada, parar mutações do cenário e preservar evidências;
uma falha deliberada prevista segue somente a observação e o encerramento definidos.
Em A1 e na condição explícita de A2, restauração é comando separado, com alvo e
configuração conhecidos, nunca efeito automático do veredito. A única exceção
automatizada é a política restrita da seção 8.5. Restaurar imagem e configuração
pertinente, não apenas a tag; registrar falha de restauração sem declarar sucesso
ou repetir automaticamente.

Depois da restauração, observar os eventos já aceitos durante o cenário sem
reentregá-los e identificar separadamente um evento novo de verificação. Este não
comprova recuperação das pendências anteriores. Trabalho BLOCKED exige o rearme
auditável previsto na aplicação, fora dos procedimentos de restauração A1/A2. Preservar lacunas,
finalizar o registro e parar os recursos dedicados conforme o procedimento local.

### 8.5. A2 — Restauração automatizada de runtime em Kind

A2 reutiliza a identidade, observação e restauração de A1. Não modifica a semântica
de seus comandos nem o aceite congelado. Comparar duas condições com o mesmo
detector, aplicação, cenário, prazos e verificação de resultado: restauração por
acionamento explícito e restauração acionada automaticamente. A diferença estudada
é o acionamento da recuperação; não atribuir ganho de detecção a essa automação.

O alvo único é `notifications-worker`. São permitidas a revisão saudável marcada
por tentativa e a falha de inicialização `DB_POOL_SIZE=0`, já exercitada em A1.
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
e classificados separadamente. Na campanha A2 original, nenhum evento foi oferecido
durante a falha de startup; o complemento da seção 8.6 tem protocolo próprio.

Separar veredito da implantação candidata, resultado da política, recuperação e
julgamento do cenário. Uma restauração bem-sucedida não aprova a implantação
defeituosa. O cenário saudável mede também restaurações indevidas; seu retorno à
base é limpeza explícita fora do intervalo de avaliação da política.

Um observador comum registra aplicação da candidata, detecção, solicitação e envio
da restauração, convergência e conclusão de negócio, usando relógio monotônico
coerente por duração e UTC para correlação. Identificar ator humano/agente/script
do acionamento explícito; execução por agente não mede tempo de reação humana.
Não acrescentar espera artificial à condição explícita. Métricas, ordem e quantidade
de repetições pertencem ao protocolo no RELEASE_PLAN.

### 8.6. Complementos A — pendência e observação inconclusiva

Preservar a série A2 concluída. Dois cenários separados usam a mesma aplicação,
workload, falha de startup, política e guarda de identidade. Não combinar falha de
implantação com falha de consulta na mesma tentativa.

**Pendência:** após confirmar a candidata `DB_POOL_SIZE=0`, admitir um evento novo,
confirmar Tracking/Order e observar publicação `SENT` com Notifications ainda
`NOT_RECEIVED`. Isso evidencia trabalho aguardando consumo; não demonstra que o
worker defeituoso recebeu/processou a mensagem nem persistência após ACK nele.
Somente então liberar o acionamento da restauração, com preparação comum às duas
condições. Registrar separadamente detecção, preparação, autorização e acionamento.
O acionamento explícito continua sendo comando separado por script, sem espera
artificial e sem representar reação humana. Revalidar identidade antes da mutação.

Observar o evento anterior exclusivamente por GET, sem reentrega ou rearme. A
infraestrutura restaura a configuração; a aplicação durável retoma o trabalho; o
verificador confirma resultado e efeito único. O evento novo de smoke da restauração
continua identificado separadamente e não substitui a verificação da pendência.

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
observar resultados. Prazos, ordem e denominadores ficam no RELEASE_PLAN.

## 9. Limites e evolução

O aceite deve identificar o ambiente efetivamente exercitado: Kind ou AKS.
O aceite local não encerra as verificações específicas da nuvem. Nenhum dos dois
marcos, isoladamente, demonstra HA, SLA de produção, capacidade, estabilidade
prolongada ou solução dos incidentes históricos da aplicação/ferramenta de medição.

A2 e seus complementos permitem somente a recuperação das seções 8.5–8.6 e
sua avaliação delimitada em Kind. HPA/KEDA, cluster autoscaler, Argo CD, canary/blue-green,
campanhas de capacidade e novos provedores de entrega continuam fora do escopo.
Autoescalonamento (B) e implantação Azure são extensões opcionais posteriores;
não são condições para concluir A2.

## 10. Ambiente local e avaliação em Kind

Kind é o ambiente principal do aceite e da comparação A2, além da preparação
funcional já realizada. Ambas as condições usam o mesmo ambiente; não misturar
tempos locais com resultados futuros de AKS. A aplicação congelada e a topologia
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
