# Manifests: alvo AKS e ambiente Kind local

A referência auditada é `campos-labs/fulfillflow`, `v1.3.0-rc.1`, SHA
`9e3a135a00db218643633c7165d3106f0c8285e1`. O overlay Kind foi executado
em cluster local. Os exemplos AKS continuam bloqueados; o ensaio local não verifica
pull ACR, identidade, isolamento de rede ou armazenamento/recuperação no AKS.

`overlays/example` é exclusivamente de validação. A imagem runtime
`example.azurecr.io.invalid/fulfillflow/runtime@sha256:` seguida de 64 zeros é
**inválida**, não resolve e não representa publicação no ACR. O seletor
`fulfillflow.io/deployment-approved=example-never-schedule` bloqueia agendamento;
nenhum nó deve receber esse label. Não aplicar este exemplo nem os bases. O overlay
real só poderá ser preparado após decisões do ambiente, aprovação de custo/acesso,
proveniência das imagens e contrato protegido de secrets. Trocar apenas a imagem
não satisfaz essas condições.

## Estrutura e ordem de implantação

| Fase | Conteúdo | Condição para avançar |
| --- | --- | --- |
| `base/foundations` | Namespace, StorageClass, policies, PostgreSQL, RabbitMQ | Secrets injetados, volumes novos, roles/bancos e broker verificados |
| `base/migrations` | Um Job Alembic por banco proprietário | Jobs concluídos e heads `1301_core`, `1203_tracking`, `1301_notifications` verificados |
| `base/runtime` | Três APIs ClusterIP e três workers, uma réplica cada | Configuração efetiva aprovada e fases anteriores verificadas |

A composição `overlays/example` une fases apenas para validação offline. Não há
um comando de deploy que aplique tudo junto. Jobs têm `backoffLimit: 0`, prazo de
300 s e preservam diagnóstico; não existe retry automático do cenário, TTL de
limpeza ou migração no startup de cada réplica. Uma nova execução no mesmo schema
exige decisão explícita após diagnóstico, sem apagar volumes. Infraestrutura não
executa o corte v1.2 → v1.3, seeds ou backup/restauração.

Renderização local, a partir da raiz deste repositório:

```powershell
& ./.tools/kubectl/kubectl.exe kustomize k8s/overlays/example
& ./.tools/kubectl/kubectl.exe kustomize k8s/overlays/example/foundations
& ./.tools/kubectl/kubectl.exe kustomize k8s/overlays/example/migrations
& ./.tools/kubectl/kubectl.exe kustomize k8s/overlays/example/runtime
```

## Contrato de secrets

Não há objetos Secret, hashes locais ou valores secretos versionados. Todos os
`secretKeyRef` e volumes de Secret são obrigatórios. No Kind, a injeção usou stdin e arquivos externos com ACL restrita; a solução
Azure ainda depende da decisão do ambiente; os nomes abaixo definem a interface.
Os arquivos protegidos, DSNs e hashes não podem aparecer em logs, argumentos com
valores, manifests versionados ou artefatos públicos. Base64 não protege um segredo.

| Secret | Chaves obrigatórias | Consumidores |
| --- | --- | --- |
| `postgres-bootstrap` | `POSTGRES_PASSWORD`, `CORE_DB_PASSWORD`, `TRACKING_DB_PASSWORD`, `NOTIFICATIONS_DB_PASSWORD` | PostgreSQL; somente inicialização de volume novo |
| `core-database` | `DATABASE_URL` | Core API/worker e migration Core |
| `tracking-database` | `DATABASE_URL` | Tracking API/worker e migration Tracking |
| `notifications-database` | `DATABASE_URL` | Notifications API/worker e migration Notifications |
| `core-runtime` | `INTERNAL_API_SECRET`, `SESSION_SECRET`, `NOTIFICATIONS_API_SECRET` | Core API/worker |
| `tracking-runtime` | `INTERNAL_API_SECRET`, `CARRIER_ALPHA_WEBHOOK_SECRET`, `CARRIER_BETA_WEBHOOK_SECRET` | Tracking API/worker |
| `notifications-runtime` | `INTERNAL_API_SECRET` | Notifications API/worker |
| `core-amqp`, `tracking-amqp`, `notifications-amqp` | `AMQP_URL` em cada Secret | Somente o worker proprietário |
| `rabbitmq-definitions` | `definitions.json` | RabbitMQ; definitions completos com hashes novos |

Os três bancos/roles são `fulfillflow_core`, `fulfillflow_tracking` e
`fulfillflow_notifications`; DSNs usam `postgresql+psycopg`, host `postgres`, porta
5432 e senha percent-encoded correspondente ao bootstrap. Cada banco revoga acesso
`PUBLIC`; as roles, não as NetworkPolicies, isolam bancos no mesmo servidor.
Senhas do administrador e de cada role devem ser distintas. O banco padrão e
`template1` também revogam `PUBLIC CONNECT`, conforme a referência.

Core e Tracking compartilham o valor de `INTERNAL_API_SECRET`. O
`core-runtime.NOTIFICATIONS_API_SECRET` corresponde a
`notifications-runtime.INTERNAL_API_SECRET` e deve ser distinto do primeiro. Os
segredos de sessão e dos dois carriers são distintos, aleatórios, com pelo menos
32 caracteres, sem placeholders. A aplicação congelada valida esses segredos por
`SERVICE_ROLE`, também nos workers; omiti-los de um worker impediria seu startup.
Jobs Alembic recebem apenas o DSN do banco proprietário e parâmetros SQL.

As AMQP URLs usam os usuários `core`, `tracking`, `notifications`, host `rabbitmq`,
porta 5672 e vhost `fulfillflow-v13`, com senhas percent-encoded. Não há usuário
admin, guest ou management exposto. O template
[assets/rabbitmq-definitions-template.json](assets/rabbitmq-definitions-template.json)
conserva os usuários sem credenciais, vhost, exchanges, filas e ACLs exatos da
referência. O arquivo **não é importável** sem completar `password_hash` para cada
usuário. Não substituir por credenciais padrão.

O helper offline `prepare_rabbitmq_definitions.py` recebe um arquivo JSON protegido
com as três chaves de usuário e senhas distintas de pelo menos 32 caracteres;
produz hashes RabbitMQ SHA256 com sal aleatório de quatro bytes e verifica que ACLs
e topologia não mudaram. Entrada/saída devem ficar fora deste repositório, em
local com ACL restrita. No Windows, o diretório protegido precisa existir antes;
o modo POSIX `0600` não configura uma ACL Windows. A saída deve ser nova, nunca
sobrescrita. O helper não injeta Secret nem imprime senhas/hashes. Exemplo de
interface, com caminhos de arquivos protegidos fornecidos pelo operador:

```powershell
python k8s/prepare_rabbitmq_definitions.py --passwords-file $ProtectedPasswordsFile --output $ProtectedDefinitionsFile
```

Bootstrap do PostgreSQL e import de definitions não são mecanismos de rotação de
senha. Não reaplicar credenciais novas presumindo atualização de volumes existentes.
A atualização de secrets por volume pode exigir reinício controlado; secrets em
env são fixos até a recriação do pod. Não há automação de rotação neste incremento.

## Recursos, segurança e saúde

Na base e em `overlays/example`, requests igualam os limites funcionais: cada API/worker `500m`/`384Mi`, PostgreSQL
`2`/`2560Mi`, RabbitMQ `500m`/`512Mi`. Total persistente: 5,5 CPU/5376 MiB; cada Job
adiciona `500m`/`384Mi` enquanto ativo. São valores provisórios para revisão, não
capacidade de nós comprovada. Rollout usa `maxSurge: 0`, `maxUnavailable: 1`; aceita
indisponibilidade com uma réplica e não promete HA. Não há HPA ou autoscaling.

No alvo AKS, PVCs provisórios: PostgreSQL 32 GiB e RabbitMQ 16 GiB, Azure Disk CSI
`StandardSSD_LRS`, binding `WaitForFirstConsumer`, reclaim `Retain`, retenção de
PVC ao excluir/escalar StatefulSet. StorageClass é recurso global e requer
permissão delimitada; seu nome/propriedade e os tamanhos precisam constar na
aprovação. Retenção continua consumindo armazenamento e não comprova backup.

PostgreSQL 18 monta `/var/lib/postgresql`, com PGDATA `/var/lib/postgresql/18/docker`.
RabbitMQ mantém StatefulSet `rabbitmq`, ordinal zero, hostname `rabbitmq-0`, nodename
`rabbit@rabbitmq-0` e PVC em `/var/lib/rabbitmq`. Esses nomes fazem parte da identidade
persistente e não podem ser renomeados ao reutilizar o volume. Cookie Erlang é criado
no volume pelo broker; não habilitar cluster/broker adicional.

APIs/workers/Jobs usam UID/GID `10001:10001` conforme Dockerfile congelado;
PostgreSQL usa `999:999`, RabbitMQ Alpine `100:101`, de acordo com as receitas
oficiais [PostgreSQL](https://github.com/docker-library/postgres/blob/master/18/trixie/Dockerfile)
e [RabbitMQ Alpine](https://github.com/docker-library/rabbitmq/blob/master/Dockerfile-alpine.template).
Os processos e permissões de volume foram exercitados no Kind. Isso não verifica
o driver CSI nem as permissões dos volumes no AKS. `fsGroup` dá escrita aos volumes; root filesystem é somente leitura,
capabilities são removidas, seccomp é padrão, token da ServiceAccount não é montado.
`/tmp` é emptyDir gravável para heartbeat; PostgreSQL tem socket gravável próprio.

APIs: startup e liveness usam `/health/live`; readiness usa `/health/ready` e
depende de banco/schema. Workers usam `fulfillflow.messaging.health` somente para
readiness. Não têm startup/liveness que mate o processo durante indisponibilidade
de dependência. Kubernetes reinicia saída do processo; travamento local sem saída
não tem recuperação garantida. Readiness falsa não suspende consumo AMQP. Todos
reservam 30 s para SIGTERM, além do encerramento limitado de 15 s da aplicação.

`APP_ENV=local` é obrigatório para preservar a validação da referência, que aceita
somente `local`, `test`, `benchmark`; isso não habilita credenciais locais ou expõe
serviços. Não inventar o valor `production`. Pools ficam API 2/0, worker 3/0.
Prefetch 8, batch 20, polling 500 ms, lease 30 s e confirm timeout 5 s são constantes
da aplicação congelada; não criar env vars ineficazes para esses valores.

## Rede

Os manifests declaram default deny ingress/egress para o namespace. Kindnet na
versão fixada suporta essas políticas, mas os testes de tráfego permitido/bloqueado
ainda não foram executados. A CI confere os seletores declarados, não o isolamento.
A regra de DNS permite somente TCP/UDP 53 para
pods `k8s-app=kube-dns` no namespace `kube-system`; revisar se o AKS aprovado usar
outro DNS/LocalDNS. Clientes SQL são os seis processos e os três Jobs. Somente os
três workers alcançam AMQP. Core API alcança Tracking/Notifications; Tracking API
alcança Core para consultas internas previstas na referência. Workers não recebem
permissão HTTP por herança dos labels das APIs.

Port-forward autenticado exige RBAC delimitado do Kubernetes; seu tráfego via
kubelet não constitui uma permissão pública de ingresso. O cliente operacional
opcional dentro do mesmo namespace precisa do label
`fulfillflow.io/operational-client=true` e só alcança Core:8000. Nenhuma permissão de
monitoring genérica, egress Internet, API server, management RabbitMQ ou SQL cruzado
é criada. Labels são configuração administrativa, não autenticação. Sem ingress,
NodePort, LoadBalancer ou serviço para workers. Métricas/tracing amplos não fazem
parte do aceite inicial.

## Origem dos assets de inicialização

`base/foundations/assets/10-services.sh` e `30-notifications.sh` derivam dos scripts
`infrastructure/init-databases.sh` e `init-notifications-db.sh` no SHA congelado.
DDL, roles, bancos e revogações foram preservados. A única mudança operacional é
ler senhas com `psql \getenv`, evitando incluí-las nos argumentos do processo;
comentários descrevem volume novo. Scripts usam LF e não executam migrações.

`rabbitmq.conf` mantém import local, move o arquivo para o diretório do Secret e
encaminha logs ao console, sem arquivo em root filesystem. O template JSON deriva
de `infrastructure/rabbitmq-v13.json`, removendo todos os três hashes locais; não
muda ACLs, bindings, durabilidade ou filas classic. Digests upstream de PostgreSQL
e RabbitMQ foram copiados do Compose congelado, sem substituição por tags mutáveis.
Nenhum código de negócio da aplicação foi copiado.

## Perfil funcional reduzido

`overlays/reduced-functional` herda o exemplo bloqueado e reduz apenas requests
de CPU. Valores estão no [DESIGN](../DESIGN.md#7-recursos-e-conclusão-assíncrona);
critérios e pendências estão no [RELEASE_PLAN](../RELEASE_PLAN.md).
Não é um overlay liberado para implantação nem comprovação de capacidade no AKS.

## Sequência operacional AKS — ainda não executada

Antes de aplicar, registrar contexto e namespace exatos, SHA da infraestrutura,
digests ACR, perfil de recursos, propriedade dos volumes e destino de evidências.
Recusar exemplos bloqueados, imagens inválidas e contexto diferente do aprovado.
Não usar o contexto corrente implicitamente em uma futura automação.

1. Conferir acesso e capacidade alocável; exportar inventário sanitizado. Reservar
   CPU/memória dos componentes do sistema além dos workloads. Não inferir capacidade
   por soma dos limits nem por quota disponível da assinatura.
2. Preparar namespace e secrets pelo canal protegido aprovado. Não incluir seus
   valores em `kubectl` argv, transcripts, logs ou artefatos de CI. Aplicar fundações
   e verificar banco/broker antes de migrations, preservando eventos e logs de falha.
3. Executar cada Job de migration separadamente: Core, Tracking e Notifications.
   A renderização conjunta da pasta não autoriza aplicação simultânea dos Jobs.
   Conferir os heads documentados e parar na primeira falha; não apagar/recriar Job
   nem volume automaticamente. Uma tentativa sucessora terá identidade própria.
4. Aplicar runtime com uma réplica por processo. Verificar rollout/prontidão com
   prazo finito, depois executar o verificador funcional existente por túnel local
   autenticado. Readiness e fila vazia não substituem conclusão do evento.
5. Exportar identificação, resultados, eventos e logs sanitizados, sem secrets.
   Preservar falhas e estados pendentes. Só retomar após classificação do problema;
   não executar o smoke de novo para ocultar timeout da tentativa anterior.
6. Ao encerrar a janela, inventariar recursos ainda cobrados e verificar a cópia
   independente antes de qualquer remoção autorizada. Parar pods não encerra custos
   de nós, discos, ACR ou rede. Não automatizar exclusão de PVCs ou resource groups.

Essa sequência é o procedimento planejado para AKS; sua implantação e seus
requisitos Azure continuam pendentes. O ambiente Kind usa as diferenças abaixo.

## Caminho Kind local

`overlays/kind-local` é o caminho local autorizado no RELEASE_PLAN. O exemplo
bloqueado e o alvo AKS permanecem intactos. Configuração do nó em
`config/kind-local.yaml`, versões/checksum em `config/kind-toolchain.json`.
Usar kubeconfig dedicado em todos os comandos; aplicar foundations, migrations
sequenciais e runtime somente depois de injetar secrets exclusivos e carregar a
imagem da referência. O agregado serve para renderização, não apply simultâneo.
Não excluir cluster/PVCs nem executar limpeza global. Enforcement das
NetworkPolicies não foi ensaiado; armazenamento local não valida Azure Disk.

### Instalação e operação local

Kind é portátil em `.tools/kind/kind.exe`, sem alteração de PATH. O binário é
verificado pelo SHA-256 em `config/kind-toolchain.json`. Docker Linux precisa estar
ativo; não ativar o Kubernetes próprio do Docker Desktop para este caminho.
O cluster criado é `fulfillflow-local-01`; usar kubeconfig dedicado, sem substituir
o arquivo global. Nenhum histórico de PostgreSQL/Compose é montado nele.

Sequência de reprodução (somente em ambiente novo): exportar o SHA congelado com
`git archive`, construir o target `runtime` com tag `fulfillflow-kind-runtime:source-9e3a135a00db`,
criar cluster com `config/kind-local.yaml`, carregar a imagem com Kind e conferir seu
ID. Injetar os secrets exclusivos pelo contrato acima, via stdin e armazenamento
protegido, antes de aplicar foundations. Aplicar cada migration separadamente,
conferir conclusão/head e só então aplicar runtime. O pacote registrado no RELEASE_PLAN contém os manifests aplicados e o procedimento
de aceite. Os helpers adicionais desse ensaio têm caminhos locais; não constituem
um instalador portátil ou pipeline de recuperação versionado.

Não executar essa sequência para retomar o cluster preservado: iniciar o mesmo
container do nó, conferir contexto/identidades e reaplicar foundations/runtime
para restaurar réplicas. Jobs e secrets já existem. Túnel do Core somente em
`127.0.0.1`; o verificador usa `scripts/verify_flow.py`, segredo em variável de
ambiente do processo e diretório novo por execução. Não usar credenciais em argv.

Para pausar, exportar evidências, escalar os workloads dedicados a zero e parar o
container do nó, preservando-o. Não o excluir: os volumes locais estão associados
a ele. Reiniciar Docker não autoriza campanha ou mudança de escopo. O estado atual
e a situação de backup/restauração pertencem ao RELEASE_PLAN.
