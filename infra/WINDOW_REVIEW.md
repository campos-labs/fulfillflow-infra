# AKS — revisão final da primeira janela

**Estado: janela executada e encerrada; protocolo histórico da verificação AKS.**
As seções abaixo preservam o protocolo aprovado; o estado efetivo consta no [RELEASE_PLAN](../RELEASE_PLAN.md) e no
[relatório técnico](../docs/AKS_PORTABILITY_EVALUATION.md).
A autorização concreta e o limite financeiro ficam no registro privado da janela.
Esta proposta reúne o que será executado; não é evidência de implantação nem um
plano Terraform real aprovado. O [guia](README.md) concentra comandos e os
[scripts Azure](../scripts/azure/) fazem geração/captura/revisão. Os auxiliares versionados não fazem apply ou destroy. A janela executada usou
orquestradores locais e operações explicitamente autorizadas, identificados nas evidências.

## Configuração delimitada

| Item | Proposta |
| --- | --- |
| Região / assinatura | Brazil South; assinatura paga e tenant conferidos, identificados somente em entradas privadas |
| AKS | Base Free, Kubernetes 1.34.11, Ubuntu, dois Standard_D4s_v6, sem autoscaling, maxSurge 1 |
| Nós | 4 vCPU/16 GiB por nó; disco SO Managed de 64 GiB; registrar imagem/OS/disco efetivos |
| Registry | ACR Basic na mesma assinatura; admin e acesso anônimo desativados; imagem da aplicação preservada |
| Workload | Referência 9e3a135, uma réplica por processo; PostgreSQL/RabbitMQ em PVCs novos 32/16 GiB Standard SSD LRS |
| Rede | Azure CNI Overlay/Cilium; API pública restrita ao IPv4 /32 do executor; sem ingresso público da aplicação; consultas por túnel loopback |
| Backend | StorageV2 Standard LRS com Entra, firewall restrito, container privado, versionamento; sem Shared Key |
| State | Backend exclusivo; keys distintas de bootstrap/environment em aks-portability/aks-portability-01/ |
| Instrumentação | Smoke existente, capturas de persistência/rede/inventário; sem KEDA/Monitor; OTel saudável opcional conforme gate abaixo |
| Duração | Até 6 h desde o primeiro recurso cobrado, reservando a última hora para encerramento; não iniciar cenário após 5 h |
| Retenção | ACR/backend por até 7 dias desde início da janela; data absoluta preenchida na autorização |

Entradas privadas já preparadas: assinatura/tenant, objeto Entra do operador,
nomes de RG/Storage/ACR/AKS, IP observado, tfvars dos dois roots e registro da janela.
Os nomes globais precisam estar disponíveis e o IP deve continuar o mesmo no início;
consulta de disponibilidade não reserva nomes. Não copiar entradas privadas para Git.
Os booleanos dos exemplos públicos permanecem falsos; a autorização efetiva fica
no registro privado. A autorização concreta pertence ao registro privado da janela.

A quota observada de 14 regional/12 Dsv6 cobre 8 vCPU normais e 12 com surge,
uso observado zero. Reconsultar imediatamente antes do apply; não cobre rotação
simultânea de todo o pool. A compatibilidade documental Ubuntu/Gen2/NVMe sustenta
a candidata, mas a disponibilidade física e aceitação pelo serviço só serão
conhecidas durante a janela. Não migrar região/SKU/versão automaticamente.

## Recursos e acessos para autorização

Criar dois RGs próprios (backend e ambiente), Storage/container, ACR, AKS,
identidade gerenciada de deploy e federação GitHub existente para main. O AKS
cria também grupo gerenciado de nós, VMSS, rede, Load Balancer, IP e discos.
PVCs criam discos adicionais; esses recursos gerenciados não constam todos como
endereços independentes no state. Não criar Monitor, Log Analytics, NAT Gateway,
Private Link ou armazenamento adicional para dumps.

| Principal | Role | Escopo | Retenção |
| --- | --- | --- | --- |
| Operador Entra identificado | Storage Blob Data Contributor | Conta exclusiva do backend | Enquanto state retido; conferir acesso substituto antes de revogar |
| Operador | AcrPush | ACR dedicado | Até fim da retenção/revisão |
| Operador | Azure Kubernetes Service Cluster User Role | AKS dedicado | Remover com cluster |
| Operador | Azure Kubernetes Service RBAC Cluster Admin | AKS dedicado | Remover com cluster; não é credencial --admin |
| Identidade kubelet | AcrPull | ACR dedicado | Remover com cluster |
| Identidade de deploy | Azure Kubernetes Service Cluster User Role | AKS dedicado | Remover com identidade/cluster |
| Identidade de deploy | Azure Kubernetes Service RBAC Writer | Namespace fulfillflow no AKS | Remover com identidade/cluster |

São sete atribuições autorizadas nos escopos acima; nenhuma aplicada no início do preflight. ARM não comprova acesso
Blob/Kubernetes. Os quatro acessos do operador são opt-in explícito no Terraform.
A federação continua restrita à main, sem ampliar para esta branch. Conferir modo
RBAC do ACR: se o serviço retornar ABAC, pausar antes de considerar AcrPull/AcrPush
suficientes; não aplicar uma alternativa de permissões silenciosamente.

## Procedimento único, com pontos de verificação

1. **Antes de gastar:** conferir autorização concreta (recursos/roles/remoção),
   identidade, IP, quotas/versão, nomes, projeção cumulativa e prazo absoluto.
   Conferir diretório privado/ACL, destino novo de evidências e inventário inicial.
2. **Backend:** plano real do bootstrap, revisão das criações/escopos e apply do
   binário aprovado. Conferir acesso Blob, container e state local protegido;
   migrar para a key exclusiva, verificar lineage/serial/leitura/locking e cópia local.
3. **Ambiente:** plano real do environment, revisão e apply aprovado; capturar
   recursos gerenciados, identidades e configuração real. Validar modo ACR,
   kubeconfig exclusivo, kubelogin e permissões. Não habilitar --admin.
4. **Imagens:** publicar/importar referências preservadas, capturar digests ACR
   reais e conferir arquitetura/proveniência. Materializar as três fases com
   `prepare_manifests.py`; nunca aplicar placeholders ou agregado sem ordem.
5. **Aplicação:** namespace, secrets novos privados, foundations, migrações/seed
   sequenciais, runtime; readiness e pull por identidade antes do smoke.
6. **Aceite:** executar uma vez `verify_flow.py`; preservar IDs e efeitos, incluindo
   a duplicata intencional. Capturar persistência, recriar apenas postgres-0 com
   contexto/UID/ownership conferidos e sem excluir PVC/PV, recapturar o mesmo evento
   e revisar. Executar sonda permitida → negada → permitida, com alvo Ready/IP/UID
   estáveis; timeout isolado não prova enforcement de NetworkPolicy.
7. **Preservação e decisão:** conferir resultados e hashes, state, manifests,
   digests, IDs de volumes, inventário e custos; concluir a seleção visual abaixo
   enquanto o ambiente existe. Só após sucesso e conferência,
   dados sintéticos podem ser descartados, conforme decisão abaixo.
8. **Encerramento:** gerar o plano seletivo descrito no guia; revisar JSON/binário,
   IDs, dependentes e exclusões implícitas do AKS. Aplicar somente o plano aprovado;
   recapturar inventário, verificar término e recursos residuais. Registrar prazo
   final de ACR/backend e não executar novo apply que recrie o cluster.

Cada comando deve encerrar no primeiro erro; uma retomada exige diagnóstico e
registro, sem repetir uma campanha inteira nem esconder tentativa desfavorável.
O procedimento é operado em etapas, não depende de construir um framework novo.
Planos reais e validações de acesso/alocação não foram executados nesta preparação.

## Captura visual durante a janela

CLI/JSON sanitizado e resultados funcionais continuam sendo a evidência primária.
Planejar somente duas capturas principais no portal Azure, em até cinco minutos
no total, aproveitando os marcos de aceite:

- AKS em operação, após o smoke aprovado e antes da remoção: escolher a visão
  mais legível de nós ou workloads, sem exigir duas telas equivalentes;
- inventário final dos recursos da janela, após a remoção: mostrar o que foi
  deliberadamente retido, vinculando a captura ao inventário CLI/JSON.

Uma terceira imagem é opcional, apenas se armazenamento, digest ACR, rede ou OTel
explicarem um resultado que as duas principais não mostram. Os demais detalhes
permanecem nas evidências estruturadas e nas tabelas do relatório.

Preferir captura direta da aba autenticada do operador durante a janela ativa,
com auxílio do executor quando disponível.
Se o acesso ao portal ou a captura não estiver disponível, fornecer o link exato
observado do recurso e avisar o operador no marco correspondente para captura
manual. Isso não pressupõe monitoramento contínuo fora da execução. Não conceder
permissões extras apenas para obter uma imagem.

Uma lista de NetworkPolicies não prova bloqueio de tráfego;
Ready não comprova conclusão de negócio. Usar os resultados das sondas e do smoke
para sustentar essas afirmações. Não expor secrets, tokens, kubeconfig ou dados
pessoais; revisar também conta/diretório e identificadores desnecessários visíveis
no portal antes de publicar.

Registrar para cada captura horário UTC, janela/cenário, legenda e arquivo CLI/JSON
que a sustenta. Preservar o original em área privada quando precisar de sanitização;
não reconstruir nem alterar visualmente o estado observado. Capturar o ambiente
ativo antes da remoção e o inventário final depois dela. A tela de custos é apoio:
seus dados podem chegar com atraso e não comprovam faturamento final ou custo zero.

Se a extensão OTel saudável for executada, preservar uma representação legível dos
spans exportados; a fatia atual não exige visualizador gráfico. Não instalar uma
plataforma apenas para obter um print. Sua captura cabe nos 45 minutos da extensão,
sem deslocar o gate de 4h15 ou a hora reservada ao encerramento. Diagramas e tabelas
podem ser produzidos depois, offline, a partir das evidências preservadas.

Antes do teardown, conferir arquivos, legibilidade e sanitização da seleção já
obtida. Uma captura ausente não justifica prolongar retenção nem recriar o cluster;
registrar a lacuna e usar a evidência primária disponível.

## Descarte e retenção definidos

**Não criar armazenamento adicional nem exigir dump completo dos dados sintéticos.**
Após aceite e conferência, preservar evidências sanitizadas, state privado,
manifests/configuração, digests, resultados funcionais, IDs de PVC/PV/volume,
inventário, custos e referências de seeds/fixtures. Conferir hashes e legibilidade.
Dados sintéticos e discos desta janela podem então ser descartados; não tocar em
volumes históricos. State/configurações sensíveis não integram ZIP público.

Se houver falha inesperada, inconsistência ou necessidade de diagnóstico, parar
**antes de remover os dados**, preservar o que já foi capturado e consultar sobre
dump/snapshot específico. Não criar snapshot/armazenamento automaticamente. Informar
custo residual e prazo de decisão; a exceção não autoriza retenção indefinida.
`Retain` de PV não protege contra remoção do grupo gerenciado pelo AKS.

| Ao final da janela bem-sucedida | Tratamento |
| --- | --- |
| AKS, identidade de deploy/federação e cinco roles dependentes do cluster | Remover por plano revisado |
| Grupo gerenciado, VMSS, LB/IP, discos de SO e dados sintéticos | Conferir remoção real; identificar e resolver resíduos antes de declarar encerramento |
| ACR, backend/container, seus dois RGs e acessos do operador a Blob/ACR | Reter até o prazo de sete dias; custo residual explícito |
| State e evidências | Conservar cópias verificadas, privadas ou sanitizadas conforme conteúdo |

A remoção final de ACR/backend exige revisão própria dos recursos retidos e de
`prevent_destroy`; não contornar proteção ou apagar state. A retenção de sete dias
não constitui agendamento automático de remoção.

## Critérios de interrupção e limites

Parar diante de falta de quota/capacidade, imagem incompatível, falha de IAM,
IP alterado, inconsistência funcional, coleta inconclusiva ou projeção acima do
limite privado autorizado. Não abrir rede, ampliar nós, reduzir recursos ou trocar
aplicação para fazer passar. Manter tempo para encerramento e consultar quando
preservar dados impedir a remoção planejada.

A preparação passou em testes locais/mocks; Kind foi comparado com v1.2.0-rc.1.
Nenhum resultado comprova ainda AKS, Azure Disk, NetworkPolicy ou RBAC efetivo.
A próxima decisão é **autorizar ou ajustar esta janela**; este documento não
concede essa autorização nem cria recursos.

## Extensão OTel saudável: preparação opcional

Pergunta complementar: quais adaptações operacionais permitem portar a aplicação
local para AKS, preservando contratos funcionais e, opcionalmente, uma capacidade
diagnóstica já validada? Não reavaliar recuperação/escala nem transferir resultados
quantitativos Kind para Azure. O aceite básico usa `9e3a135`; a fatia HTTP usa
`045e1ca`, com imagem/digest próprios e APIs diagnósticas separadas.

A preparação da extensão está autorizada; execução/custos/roles da janela ainda
não estão. Antes de autorizar a janela, incluir explicitamente a extensão saudável
se desejada. O gate não é permissão autônoma: exige autorização da janela e da
extensão, aceite básico concluído, evidências preservadas, nenhuma pendência,
capacidade conferida, custo dentro do limite e nenhum novo serviço/role Azure.
Começar até 4h15 desde o primeiro recurso cobrado, no máximo 45 minutos incluindo
captura/restauração dos recursos diagnósticos, preservando uma hora de encerramento.
A ausência de oportunidade encerra a janela básica normalmente, sem exigir OTel.

`prepare_http_trace.py` materializa offline clones Core/Tracking, receptor, três
Services, ConfigMap e NetworkPolicy. Recebe o runtime AKS já materializado, imagem
instrumentada por digest ACR, registro privado do gate e window ID. Não aplica
objetos ou executa o piloto Kind. Geração pode ocorrer com gate fechado; aplicar
requer reavaliar o gate no instante de início. A imagem instrumentada deve ter
proveniência conferida e capacidade dos três pods deve caber no pool existente.

```powershell
python scripts/azure/prepare_http_trace.py --runtime $RuntimeYaml --image $InstrumentedAcrDigest --registry $AcrLoginServer --window $WindowId --gate $PrivateGate --output $NewDiagnosticManifests
```

O registro do gate usa os booleanos `window_authorized`,
`healthy_extension_authorized`, `basic_acceptance_complete`, `evidence_preserved`,
`no_pending_issue`, `cost_within_authorized_limit`, `no_new_azure_resources_or_roles`,
`capacity_verified`, `prepared_and_reviewed`, mais `elapsed_seconds`. São declarações
vinculadas às evidências da janela, não descobertas automaticamente pelo gerador.

Na execução futura: conferir ausência de colisão dos oito nomes; criar apenas os
recursos diagnósticos; aguardar prontidão e conferir sink→Core, Core→Tracking e
Tracking→Core; consultar uma vez o evento já concluído com o observador existente;
recolher resultado e snapshot OTLP com exportação limitada; usar `verify_trace`
para quatro spans/parentage/rotas/status e confirmação funcional independente.
Conservar também digests, configuração, hashes e limites. Remover somente os oito
objetos criados, por UID/ownership conferidos, antes do encerramento geral. Nunca
usar o executor histórico que inicia/para Kind nesta janela AKS.

Os comandos de leitura usam kubeconfig/contexto explícitos. Depois das verificações
anteriores, a consulta única é:

```powershell
& $Kubectl --kubeconfig $PrivateKubeconfig --context $Context -n fulfillflow exec deployment/httpdiag-sink -- python /diag/http_trace_observer.py $ExternalEventId $InboxEventId $TrackingEventId
```

Preservar stdout como `functional.json` mesmo se o retorno for não zero, sem
repetir a consulta. Capturar `/snapshot` dentro do receptor por `kubectl exec`,
com timeout HTTP de 2 s, até dez leituras separadas por 1 s; guardar
`trace-records.json`. Essas leituras são do receptor, não novas consultas de negócio.
O contrato `scripts.http_trace_contract.verify_trace(snapshot, functional)` é o
mesmo da v1.2 e deve rejeitar resposta incompleta ou cobertura/parentage incorretos.
Não interpretar readiness do receptor como confirmação de exportação.

O preparo não é ensaio AKS; valores reais e identidades devem ser conferidos ao
conectar os comandos ao contexto da janela. Não desenvolver outro cenário enquanto o cluster cobra.
Saudável satisfatório demonstra a portabilidade desta fatia, não cobertura completa,
melhoria de diagnóstico, overhead ou equivalência de desempenho.

**Segundo gate:** falha 200→503→200 não está pré-autorizada. Só propor após o
saudável se existir uma pergunta adicional concreta; não manter o cluster esperando
indefinidamente. Azure Monitor/Application Insights permanece fora da janela.
Sua avaliação posterior deve comparar Collector OTLP e distro/exportador sem
presumir mudança da aplicação. A documentação distingue Collector de integração
AKS/AMA em preview; nenhuma feature foi registrada nesta preparação.
[Opções Microsoft](https://learn.microsoft.com/en-us/azure/azure-monitor/containers/opentelemetry-options).

## Emenda autorizada: OTel isolado

Em 2026-09-28, após recusa por requests insuficientes, o operador autorizou uma
única tentativa saudável com suspensão temporária de core-worker, tracking-worker
e notifications-worker. Antes: prontidão, resultado funcional preservado, ausência
de pendências em inbox/outbox, quarentena e filas do broker, e captura do Portal
com todos os workers ativos. Registrar UIDs e réplicas; liberar requests por
suspensão, sem reduzir recursos ou ampliar nós/SKU. Revalidar ausência de trabalho
após suspensão, executar uma consulta do evento concluído e recolher quatro spans.
Remover diagnósticos por UID, restaurar workers inclusive em falha, conferir
prontidão e parar AKS. A captura tem prazo de três minutos, sem bloquear encerramento.
Essa emenda não demonstra coexistência com todos os workers nem altera o aceite
básico, os limites financeiros privados, a janela original ou a autorização de remoção.

O encerramento seletivo usa plano `-destroy` com os oito endereços explícitos.
Terraform marca `complete=false` em planos com `-target`; isso não é tratado como
convergência integral. O revisor exige lista de targets da invocação exatamente
igual ao inventário aprovado, plano aplicável, ausência de drift/adiamentos e
somente as exclusões por ID esperadas. O modo padrão continua recusando planos
incompletos. Fonte: https://github.com/hashicorp/terraform-json/blob/main/plan.go
