# Kubernetes: operação Kind e referência AKS

A referência auditada é `campos-labs/fulfillflow`, `v1.3.0-rc.1`, SHA
`9e3a135a00db218643633c7165d3106f0c8285e1`. O overlay Kind foi executado
em cluster local. Os exemplos AKS continuam bloqueados; o ensaio local não verifica
pull ACR, identidade, isolamento de rede ou armazenamento/recuperação no AKS.

Este guia descreve configuração e comandos. Começar pelo [Kind local](#caminho-kind-local),
[verificação e restauração explícita](#verificação-e-restauração-explícita),
[restauração automática](#restauração-automática) ou
[trabalho pendente e inconclusão](#trabalho-pendente-e-observação-inconclusiva).
Resultados e fontes estão na [avaliação operacional](../docs/OPERATIONAL_EVALUATION.md);
entregas, pausa e extensões, no [RELEASE_PLAN](../RELEASE_PLAN.md).

**Extensão v1.1 em reavaliação:** calibração, piloto KEDA e diagnósticos
usam cluster dedicado, sem reutilizar bancos/volumes históricos. Os comandos
específicos estão abaixo; sua disponibilidade não autoriza nova carga durante a
[pausa registrada](../RELEASE_PLAN.md#fechamento-do-diagnóstico-de-consulta-e-memória).
Não usar `resume`/`pause` da base ou reaplicar o runtime sobre um alvo controlado
por KEDA/HPA: esses comandos restauram/escalam réplicas sem coordenar o controlador.

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
env são fixos até a recriação do pod. Não há automação de rotação nesta entrega.

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
parte do aceite.

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
conferir conclusão/head e só então aplicar runtime. O pacote local de implantação,
identificado no [histórico de entrega](https://github.com/campos-labs/fulfillflow-infra/blob/47dbd111ad4eff89a8e64c7b50d7d2c59c23baf7/RELEASE_PLAN.md),
contém os manifests aplicados e o procedimento de aceite. Os helpers adicionais desse ensaio têm caminhos locais; não constituem
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

## Verificação e restauração explícita

A interface segue [DESIGN §8.1–8.4](../DESIGN.md#81-verificação-de-uma-revisão-de-runtime).
Usa Kind existente e uma alteração em um único Deployment; não cria cluster, secrets
ou migrations. Nomes dos scripts/configurações são preservados como interfaces
existentes, sem representar etapas pendentes de implementação.

Interface: `scripts/Invoke-A1.ps1 -Python <executável> -Config <arquivo.json>
-OutputDirectory <destino-novo> -Mode <modo>`. O equivalente Python é
`scripts/a1.py --config <arquivo.json> --output <destino-novo> --mode <modo>`.

| Modo | Efeito |
| --- | --- |
| `status` | Confere contexto, UID, ferramentas e inventário sem alterar workloads |
| `resume` | Inicia somente o nó existente e restaura réplicas, sem repetir bootstrap/migrations |
| `attempt -Scenario healthy` | Marca uma revisão saudável, verifica sua identidade e o fluxo completo |
| `attempt -Scenario invalid-pool` | Altera apenas DB_POOL_SIZE do notifications-worker e verifica a falha de inicialização esperada |
| `restore -Source <tentativa>` | Restaura a configuração salva, observa evento anterior quando identificável e confere um evento novo |
| `pause` | Escala workloads dedicados a zero, aguarda parada e interrompe o nó, preservando dados |

O exemplo [a1.example.json](../config/a1.example.json) é deliberadamente incompleto.
Criar a configuração real fora do Git: caminhos absolutos das ferramentas/kubeconfig,
contexto, nome do nó, UID observado do namespace e imageID local conferido. Não copiar
UID/digest de outra implantação. Prazos padrão: 600 s por operação, 90 s por rollout,
90 s por fluxo; polling de 1 s. Cada comando exige destino novo e não repete mutações.
O segredo do webhook entra somente pela variável de processo
`CARRIER_ALPHA_WEBHOOK_SECRET`, nunca por argumento ou arquivo versionado.

Resultado `scenario_passed=true` não significa implantação aprovada: o cenário de
falha pode passar com `deployment_verdict=rejected`. Falta de evidência permanece
inconclusiva. `restore` é sempre uma chamada explícita; não é acionado por `attempt`.
Antes de retomar no Windows, conferir se a porta da API continua livre e publicada
pelo Docker. Se estiver reservada pelo sistema, interromper; não excluir reservas
ou recriar o cluster preservado como reparo automático.

Sequência operacional, quando autorizada:

1. Conferir ferramentas, contexto, namespace, imagens e recursos dedicados. Retomar
   o ambiente preservado pelo procedimento acima e verificar sua referência saudável;
   preparação de ambiente novo, quando necessária, é separada da avaliação. Não excluir
   ou reutilizar recursos históricos, regenerar secrets ou repetir migrations concluídas.
2. Registrar o workload-alvo, configuração saudável restaurável e candidata,
   consumidores de qualquer configuração compartilhada e comandos de restauração.
   Renderizar/conferir o diff restrito ao runtime e preservar configuração não sensível.
3. Preparar destino novo por tentativa, expectativa, prazos, IDs e consultas de
   conferência. Executar o cenário saudável e a falha selecionada em tentativas
   separadas, com a referência saudável restabelecida entre elas.
4. Aplicar somente a mudança delimitada; registrar geração, ReplicaSet, pods,
   imagem/configuração efetivas, rollout e probes. Conferir a revisão exercitada
   antes de atribuir resultado funcional; nenhuma mutação automática para reparar falha.
5. Observar conclusão por etapa e preservar o veredito separado do julgamento do
   cenário. Na falha prevista, seguir o encerramento preparado; na inesperada, parar
   mutações e diagnosticar. Não reenviar eventos nem substituir registros anteriores.
6. Restaurar explicitamente a revisão/configuração saudável e conferir tanto os
   eventos aceitos durante a tentativa quanto um novo evento identificado. Registrar
   pendências e eventuais falhas de restauração. Exportar evidências e parar os
   recursos dedicados, preservando dados. Respeitar o encerramento previsto no plano.

A verificação isolada não instala HPA/KEDA, rollback automático ou novas ferramentas
de observabilidade. Seus testes não substituem a execução integrada nem validam AKS.

## Restauração automática

A política reutiliza a configuração local da verificação explícita e segue
[DESIGN §8.5](../DESIGN.md#85-restauração-automatizada-de-runtime-em-kind).
ACR não é necessário: o Kind usa a imagem local verificada, sem publicação externa.

Interface: `scripts/Invoke-A2.ps1 -Python <executável> -Config <arquivo.json>
-OutputDirectory <destino-novo> -Mode <modo>`. O equivalente Python é
`scripts/a2.py --config <arquivo.json> --output <destino-novo> --mode <modo>`.

| Modo | Efeito |
| --- | --- |
| `run -Condition auto -Scenario healthy` | Verifica a candidata saudável; não restaura automaticamente |
| `run -Condition auto -Scenario invalid-pool` | Restaura uma vez somente após rejeição de startup comprovada; verifica conclusão funcional |
| `run -Condition explicit -Scenario <cenário>` | Usa o mesmo observador; na falha elegível aguarda solicitação separada dentro do prazo |
| `request -Source <tentativa> -Actor <human/agent/script>` | Registra solicitação atômica em outro terminal; não altera o cluster diretamente |
| `recover -Source <tentativa> -Actor <ator>` | Encerramento explícito ou reconciliação após interrupção; exige destino novo e valida identidade/configuração |

Usar `Invoke-A1.ps1` nos modos `resume`/`pause` para o ciclo de vida do laboratório
existente. O segredo continua entrando apenas pela variável de processo `CARRIER_ALPHA_WEBHOOK_SECRET`.
`request` dispensa esse segredo e não disputa o lock mantido pelo observador.
Registrar o ator real; acionamento por script/agente não mede reação humana.

Cada execução usa destino novo. O journal registra intenção antes de mutação e
etapas de decisão/recuperação. Após interrupção, preservar a tentativa: uma intenção
antiga com resultado incerto não autoriza reenviar o patch. Aceitação HTTP desconhecida
não autoriza reenviar evento. `recover` pode recusar a retomada e exigir diagnóstico.
Não editar o journal para destravar a operação.

No cenário saudável, chamar `recover` explicitamente para a limpeza entre tentativas;
essa limpeza não conta como recuperação automática. O comando confere evento anterior
por consulta, quando identificável, e um fluxo novo com duplicata controlada. Repetir
uma recuperação já iniciada somente observa seu evento conhecido; não cria substituto.
Uma candidata rejeitada continua rejeitada mesmo quando sua restauração é aprovada.

Antes da execução, conferir Docker, porta da API, contexto/UID, recursos e ausência
de carga concorrente. Não excluir volumes, repetir bootstrap/migrations ou modificar
probes. Parar na primeira falha inesperada, preservar evidências e encerrar o laboratório.

## Comparação de acionamento

**Ciclo concluído; comandos abaixo são referência operacional.** A série 03 foi
conferida com 20/20 tentativas e ambiente parado. Não repetir para este aceite;
resultados estão no [relatório operacional](../docs/OPERATIONAL_EVALUATION.md#3-acionamento-e-restauração-da-configuração)
e a pausa, no [RELEASE_PLAN](../RELEASE_PLAN.md). Uma futura execução
exige decisão, referência e destino próprios, sem sobrescrever as séries existentes.

`scripts/Invoke-A2Comparison.ps1 -SettingsFile <arquivo-local.json> -Mode Check`
faz a conferência inicial sem iniciar o Kind ou criar o destino de coleta.
`-Mode Execute` retoma o laboratório existente, congela o protocolo, executa as
20 tentativas e tenta parar o ambiente ao concluir ou interromper. A política de
restauração permanece inalterada; não há reposição automática, novo cluster ou recurso Azure.

O arquivo local, fora do Git, contém caminhos absolutos: `python`, `config`
(configuração operacional conferida), `output` (destino novo), `secret_file` (JSON privado
existente, campo `alpha`) e `expected_sha` (commit limpo aprovado). Valores de
segredos nunca entram nesse arquivo nem nos argumentos. O launcher carrega o segredo
apenas no ambiente do processo e restaura a variável anterior ao sair.

Manter Docker Desktop disponível, alimentação AC, tampa aberta e sessão ativa;
não executar builds, outras cargas ou modificar arquivos/configurações durante a
janela. O executor recusa containers concorrentes, confere energia entre tentativas
e inibe temporariamente o desligamento ocioso de tela/sistema no Windows. Não altera
o plano persistente nem impede suspensão deliberada, fechamento da tampa ou falha
do host. Não é monitoramento contínuo de energia/sessão durante cada tentativa.

O acionamento explícito usa subprocesso independente, identificado como `script`;
o observador continua responsável pela restauração. A espera de solicitação usa
polling de 0,1 s; a observação mantém 1 s. A leitura de log vazio de startup pode
aguardar até 5 s, com identidade conferida; isso integra a detecção e não repete a implantação. Não há atraso artificial. Os tempos
de limpeza das candidatas saudáveis ficam fora da avaliação da política.

São até quatro horas, reservando 30 minutos para limpeza, verificações e pausa.
Uma falha inesperada interrompe a série: não restaurar automaticamente um resultado
incerto. A pausa preserva o estado e pode deixar configuração candidata para análise.
Se a própria pausa falhar, o resumo registra isso; não presumir que o nó parou.
Encerrar o terminal à força pode impedir finalização/exportação.

Saídas: `protocol.json`, hash do protocolo, pastas por tentativa, journals,
`attempts.csv`, `summary.json`, `checksums.sha256` e ZIP ao lado do destino.
O resumo separa aprovação do cenário, aptidão para agregação, erro operacional e
encerramento. Pares incompletos não entram nas diferenças; falhas não viram tempos
de sucesso. Saída zero exige as 20 tentativas e encerramento aprovado.
Se houver erro, preservar tudo e não repetir o comando ou trocar o destino para
completar a quota. Consultar o diagnóstico antes de qualquer nova execução.

## Trabalho pendente e observação inconclusiva

**Ciclo encerrado:** avaliação 01 conferida, 9/9 tentativas; laboratório parado.
Os comandos abaixo documentam a interface. Não repetir a série concluída;
nova execução depende de protocolo/destino próprios e decisão após a pausa.

Protocolo executado e resultados: [avaliação operacional](../docs/OPERATIONAL_EVALUATION.md#2-referências-e-método);
estado: [RELEASE_PLAN](../RELEASE_PLAN.md); contratos: [DESIGN §8.6](../DESIGN.md#86-trabalho-pendente-e-observação-inconclusiva). O executor
`scripts/Invoke-AComplements.ps1` usa os mesmos campos locais do launcher de comparação
(`python`, `config`, `output`, `secret_file`, `expected_sha`). `output` deve ser novo.
Para avaliação, acrescentar `pilot_source`, apontando ao pacote completo dos três
pilotos com checksums e a mesma implementação dos scripts. Não versionar settings,
segredos ou caminhos locais.

```powershell
# Conferência sem mutação; caminhos de executáveis devem ser verificados.
pwsh -NoProfile -File scripts/Invoke-AComplements.ps1 -SettingsFile <settings-local.json> -Mode Check -Stage pilot
# Três pilotos; fora das nove tentativas de avaliação.
pwsh -NoProfile -File scripts/Invoke-AComplements.ps1 -SettingsFile <settings-local.json> -Mode Execute -Stage pilot
# Somente após pilotos e CI aprovados; outro settings/output, contendo pilot_source.
pwsh -NoProfile -File scripts/Invoke-AComplements.ps1 -SettingsFile <settings-local.json> -Mode Execute -Stage evaluation
```

O launcher retoma somente o Kind identificado, exige AC no Windows, ausência de
containers concorrentes, referência congelada e diretório novo. Para na primeira
falha inesperada, preserva dados e tenta pausar o laboratório. Não há retry ou
reposição. Se uma tentativa falhar, consultar `summary.json` e o journal antes de
retomar: pausa de recursos não equivale a restauração de configuração.

Os tempos de sinais paralelos incluem consultas/polling; o CSV dos complementos
não integra as medianas da comparação de acionamento. A falha 503 é injeção
identificada no transporte do observador, não indisponibilidade real da API. A abstenção é verificada
antes da limpeza explícita. A retomada dos eventos anteriores usa apenas GET.

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

Essa sequência pertence à extensão opcional AKS; implantação e requisitos Azure
continuam pendentes. O aceite Kind não a substitui.


<a id="calibracao-de-concorrencia"></a>
## Calibração de concorrência — preparação da v1.1

`scripts/Invoke-ScaleCalibration.ps1` opera exclusivamente `fulfillflow-scale-01`,
com kubeconfig e credenciais privados fora do repositório. Não usar os comandos
de retomada do laboratório histórico. Requer Docker Linux, imagem local congelada,
ferramentas verificadas e `uv sync --frozen --group autoscaling`.
`Prepare` cria o ambiente uma única vez; `Calibrate` exige identidade preservada,
checkout limpo e nenhuma outra carga Docker. Nunca reutilizar saída existente ou
apagar lock sem investigar seu dono.

```powershell
# $private: diretório protegido criado no bootstrap; não versionar seu conteúdo.
./scripts/Invoke-ScaleCalibration.ps1 -Mode Calibrate -PrivateDirectory $private -OutputDirectory ./artifacts/scale-calibration-01
```

Manter o equipamento ligado e sem suspensão. O comando prepara entidades sintéticas,
exercita uma e duas réplicas fixas e para o nó ao terminar, preservando volumes.
Encerramento forçado exige conferir o container antes de retomar. Saídas incluem
identidades, admissões, observações por evento, séries, resumos e hashes.
Aceite desconhecido não provoca reenvio. Tempos são limites superiores observados,
sujeitos à duração e concorrência das consultas. Guardar o resultado e reavaliar
antes de KEDA; não repetir com carga maior para obter diferença. Esta preparação
não comprova autoscaling nem altera as campanhas encerradas da v1.0.0.

A sucessora `scale-calibration-05` mantém o perfil de entrada. `admission.jsonl`
acrescenta `dispatch_attempt` (horário previsto/real, atraso, concorrência e motivos).
`series.jsonl` é coletado independentemente da observação funcional e inclui duração
e atraso do ciclo, recursos dos processos e memória do host. Erro aparece em
`series.error.json` e impede aceite. `worker-attribution.json` vincula os aceites
aos logs DONE por pod, sem exportar texto livre de logs. `summary.json` distingue
conclusão funcional e completude da atribuição. `shutdown.json` confirma a parada.
Amostragem de processos pode omitir subprocessos curtos; não somar consumos do host
e do nó. Preservar todas as saídas, inclusive quando `complete=false`.


## Piloto mínimo KEDA

`Invoke-KedaPilot.ps1` reutiliza o cluster exclusivo e o diretório privado existente.
`Prepare` instala a versão fixada, verifica a consulta, injeta erro SQL apenas no
scaler, restaura a consulta e remove seu ScaledObject/HPA antes de parar o nó.
`Execute` repete essas verificações, aplica a mesma carga da calibração com política
adaptativa e observa mais 360 s. Cada modo exige saída nova e checkout limpo.
Não executar a calibração fixa enquanto existir controlador de escala.

```powershell
./scripts/Invoke-KedaPilot.ps1 -Mode Prepare -PrivateDirectory $private -OutputDirectory ./artifacts/keda-preparation-01
./scripts/Invoke-KedaPilot.ps1 -Mode Execute -PrivateDirectory $private -OutputDirectory ./artifacts/keda-pilot-01
```

A configuração é `config/keda-pilot.json`. Manifesto oficial core é baixado com hash
conferido, sem instalar Helm ou webhook adicional. A instalação requer rede para
GitHub/GHCR; não usa Azure. `keda-install.yaml`, `keda-identities.json`, `policy.json`, `metric-availability.json`,
`metric-fault-probe.json`, séries e logs permitidos sustentam a conferência.
A credencial própria do scaler fica em `keda-reader.json` no diretório privado;
não anexar esse diretório. Aplicativos empacotados no Windows podem redirecionar
AppData: usar o caminho físico acessível pelo terminal, preservando os mesmos arquivos.
Ao terminar, conferir resumo, hashes e `shutdown.json`. Não apagar CRDs ou volumes.
Falha de encerramento requer investigação antes de nova execução.

Referências técnicas: [instalação](https://keda.sh/docs/2.20/deploy/),
[scaler PostgreSQL](https://keda.sh/docs/2.20/scalers/postgresql/) e
[ScaledObject/HPA](https://keda.sh/docs/2.20/reference/scaledobject-spec/).

### Diagnóstico retrospectivo do piloto

`uv run --frozen python scripts/review_scale_pilot.py --input artifacts/keda-pilot-04/adaptive --output artifacts/scale-diagnostic-01`

Lê somente evidências locais já preservadas, conta respostas GET, agrupa CPU por
UID/timestamp da fonte e calcula intervalos do patamar. Exige destino novo e
separado; não inicia Docker nem Kubernetes. Se o destino já existir, use outro
identificador para reprodução. O resultado inclui limites e hashes das entradas.

### Coleta focal de throttling e consultas

`Invoke-ScaleDiagnostic.ps1` executa uma condição fixa, por padrão de 300 eventos.
Usa a identidade e as guardas da calibração; exige Docker disponível, checkout
limpo, destino novo e nenhum outro contêiner em execução. Recusa controlador
ativo sobre o worker e contadores de throttling ausentes antes de oferecer carga.

```powershell
$scalePrivate = Join-Path $env:LOCALAPPDATA 'Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\FulfillFlowInfra\scale-01'
.\scripts\Invoke-ScaleDiagnostic.ps1 -PrivateDirectory $scalePrivate -OutputDirectory '.\artifacts\scale-instrumentation-01'
```

`fixed-1/series.jsonl` acrescenta contadores cAdvisor e timestamps da fonte;
`fixed-1/event-*/http-timings.json` contém tempos do transporte, status ou tipo
de erro, sem corpo completo, headers completos ou identificadores de URL.
Na versão 2, inclui IDs UUID de correlação e códigos de problema permitidos;
campos ausentes nas coletas anteriores não significam ausência de erro. Tempos são exportados ao
encerramento; encerramento abrupto pode perder o buffer, sem autorizar inferir
zero consultas. Aplicam-se as ressalvas e a pausa do RELEASE_PLAN.

Revisão sem nova carga (saída nova, fora do pacote original):

```powershell
uv run --frozen python scripts/review_scale_diagnostic.py --input artifacts/scale-instrumentation-01 --output artifacts/scale-instrumentation-01-review.json
```

Confere o manifesto de hashes, deduplica timestamps, identifica resets e registra
janelas por cgroup. Percentuais de períodos com throttling não medem perda de CPU
ou indisponibilidade. Resultados locais e decisão estão no RELEASE_PLAN.

Para a avaliação optativa de reutilização das duas respostas terminais:

```powershell
.\scripts\Invoke-ScaleDiagnostic.ps1 -PrivateDirectory $scalePrivate -OutputDirectory '.\artifacts\scale-instrumentation-reuse-01' -ReuseTerminalReads
```

Modo exclusivo do diagnóstico. Preserva todas as asserções e identifica a
mudança de instrumento no protocolo; não utiliza cache entre observações.

### Janela reservada para medições

Concluir downloads e conferência de dependências antes de reservar o host.
Durante a preparação das entidades, oferta, drenagem e exportação, manter
alimentação/perfil estáveis e evitar outros aplicativos, builds ou clusters.
Execução direta pelo PowerShell independe da continuidade do chat. O diagnóstico
fixo usa o ambiente local já preparado; disponibilidade offline exige imagens,
Python, bibliotecas e executáveis presentes. Não fazer alterações de rede no meio
da coleta. Liberar a janela após conferir `summary.json` e `shutdown.json`.
Os critérios de interferência e os limites dos diagnósticos ficam no RELEASE_PLAN.

Referência limpa preparada para execução manual, após reservar o host:

```powershell
.\scripts\Invoke-ScaleDiagnostic.ps1 -PrivateDirectory $scalePrivate -OutputDirectory '.\artifacts\scale-clean-reference-01' -ReuseTerminalReads -ControlledHost
```

`ControlledHost` exige o modo de reutilização e alimentação pela tomada.
Os registros `host-conditions.jsonl`/`host-review.json` qualificam separadamente as
condições observadas, sem comprovar exclusividade do host. Mudança detectada invalida
a qualificação temporal, mas não aborta imediatamente a oferta nem apaga efeitos.
Aguarde `JANELA ENCERRADA` e confira o resumo; um aviso de encerramento não confirmado
exige verificar o Docker. O script não fecha programas ou altera energia/rede.

Na inicialização, a pré-verificação aguarda os contadores de throttling por
até 90 s, com consultas limitadas a 10 s. O diário `throttling-startup.jsonl`
preserva ausências e disponibilidade; erro persistente termina antes da oferta.
Essa espera não se aplica às amostras durante a carga. A tentativa `01` foi
preservada e `scale-clean-reference-02` concluiu a referência controlada. Não
reutilizar essas pastas; a próxima carga depende do protocolo de caracterização
registrado no RELEASE_PLAN.

Caracterização fixa delimitada: o mesmo launcher aceita `-PeakRate 12` ou
`-PeakRate 16`, obrigatoriamente com `-ControlledHost -ReuseTerminalReads`.
Usar pasta exclusiva por execução e respeitar o gate entre taxas no RELEASE_PLAN;
não executar os dois comandos em paralelo ou em laço incondicional.

A caracterização `scale-capacity-12-01` atingiu o limite de concorrência do
gerador (22 ofertas não realizadas; 398/398 aceites concluídos). O gate impediu
a execução de 16/s. Não repetir nem aumentar a taxa automaticamente; preservar
os registros e definir um protocolo sucessor antes de mudar o instrumento.

Diagnóstico sucessor de admissão: acrescentar `-HttpConcurrency 16` somente com
`-PeakRate 12` ou `-PeakRate 16`, sempre com `-ControlledHost -ReuseTerminalReads`,
em pasta nova. Os demais
parâmetros permanecem iguais; consultar a justificativa e os limites no RELEASE_PLAN.

A opção `-PlateauSeconds 45` exige `-PeakRate 12 -HttpConcurrency 16`,
`-ControlledHost -ReuseTerminalReads` e mantém o teto de 600 eventos; o padrão
continua em 30 s. A sucessora manual recuperou margem e concluiu sem erro HTTP;
o diagnóstico a 16/s por 30 s, teto HTTP 16 e 540 eventos também concluiu.
O 503 anterior permanece sem causa determinada. `complete=true` não substitui as guardas
de progressão. Não reutilizar destinos nem executar outra carga antes de reavaliar
os limites registrados no RELEASE_PLAN.

O diagnóstico de capacidade adicional aceita `-FixedReplicas 2` somente com
`-PeakRate 16 -HttpConcurrency 16 -PlateauSeconds 30`, controle do host e
reutilização terminal. Usa pasta nova `fixed-2` dentro da saída da tentativa;
o revisor identifica a condição pelo protocolo. O padrão continua uma réplica.
Essa condição aumenta recursos totais dos workers, sem autoescalonamento;
seguir objetivo e guardas no RELEASE_PLAN antes de qualquer execução.

Piloto adaptativo sucessor: `Invoke-KedaPilot.ps1 -Mode Execute -CapacityProfile`
(com `-PrivateDirectory` e `-OutputDirectory` exclusivos) seleciona o perfil
limitado de 540 eventos, uma réplica inicial, HTTP 16, captura v2, reutilização
terminal e controle do host. O padrão histórico permanece 300 eventos. Usar o
launcher local preparado no RELEASE_PLAN para conferir 5 GiB livres e isolar
a janela. Aguardar também os 360 s de observação após a carga e o encerramento.
O teste não exige escala: avaliar sinal, disponibilidade da métrica, decisões e
participação por pod. Parar para revisão, mesmo com `complete=true`.

A sucessora adaptativa com `qualification_version=2` aplica a guarda de 2 GiB
por fase antes da oferta e nos pontos de controle seguintes; violação anterior
amostrada impede continuação. `host-phases.jsonl` localiza o bloqueio.
O launcher `Invoke-KedaCapacity02.local.ps1` identifica uma tentativa, sem retry.
Oferta incompleta pode preservar observação posterior somente com host seguro,
aceitos concluídos e atribuição íntegra; não transforma a tentativa em aprovada.
Conferir `post-load-outcome.json` e registros incrementais mesmo em interrupção.
