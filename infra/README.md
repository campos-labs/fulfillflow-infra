# Terraform — preparação da portabilidade Azure

A janela de 28/09/2026 foi executada e encerrada. O
[relatório técnico](../docs/AKS_PORTABILITY_EVALUATION.md) reúne resultados e
limites; o [plano atual](../RELEASE_PLAN.md) identifica a entrega. AKS e recursos de execução foram removidos.

Este guia descreve configuração e procedimentos reutilizáveis, sem autorizar uma
nova janela. A [revisão da janela](WINDOW_REVIEW.md) preserva o protocolo aprovado.
A extensão usa ACR/AKS na mesma assinatura e permanece separada do Kind. O
[DESIGN](../DESIGN.md#89-verificação-de-portabilidade-para-aks) define os contratos.

Dois roots independentes usam Terraform **1.13.5** e AzureRM **4.55.0**, com locks
para Windows/Linux amd64: `bootstrap/` prepara o backend persistente;
`environment/` descreve AKS, ACR e identidade de deploy. Não há provider Kubernetes
nem instalação de aplicações nesses roots. A proposta usa uma região, capacidade
fixa e namespace dedicado, começando com uma réplica por processo. Tamanhos e
quantidade de nós dependem do dimensionamento e orçamento aprovados.

Os valores em `*.example` e nos testes são sintéticos. Assinatura, região, quotas,
SKUs, versão AKS, capacidade e orçamento exigem conferência antes de provisionar.
`cost_approval_confirmed` é falso por padrão: a precondição bloqueia plan/apply
sem confirmação e referência da aprovação. Essa guarda evita execução acidental;
alterar o booleano não concede autorização. Nenhum benefício de assinatura ou
saldo presumido equivale a teto de gasto aprovado. Esta documentação não autoriza
criação de recursos. [config/aks-portability.json](../config/aks-portability.json) mantém
somente requisitos públicos de preparação, sem valores de autorização.
O registro privado da janela pode ficar fora do checkout ou em arquivo local
com exclusão do Git conferida; não copiá-lo para logs, CI ou pacotes publicados.
A revisão final identifica a configuração executada. Qualquer nova janela exige
autorização e planos reais próprios; a autorização histórica não é reutilizável.

## Descoberta e decisão de provisionamento

A descoberta inicial usa apenas leituras, com assinatura explícita e saídas
sanitizadas. Não executar `apply`, registrar providers, criar usuários/roles ou
habilitar produtos para descobrir se a conta os suporta. Se autenticação ou
permissão impedir uma leitura, registrar a lacuna e a intervenção necessária.

| Conferência | Evidência necessária |
| --- | --- |
| Conta e identidade | Assinatura habilitada, tenant, oferta/cobrança e permissões efetivas; separar usuário Entra, assinatura e conta de faturamento |
| Alocação | Regiões candidatas, providers já registrados, versão AKS GA, quota regional e por família, restrições da SKU e margem para manutenção |
| Dimensionamento | Requisitos de system pool, capacidade alocável, sistema, runtime, Jobs e volumes; evitar selecionar VM apenas pelo preço ou catálogo |
| Rede e executor | Egress aprovado, API restrita, ranges sem sobreposição, acesso ao backend e paths permitidos/bloqueados previstos |
| Imagens e acesso | ACR Basic, modo RBAC/ABAC, push do operador e pull do kubelet; permissões do bootstrap, provisionamento e deploy separadas |
| Custo e encerramento | Estimativa por recurso/fase, duração, contingência, retenção com data e procedimento de parada/remoção verificável |

**Free é a preferência para o gerenciamento do cluster**, não gratuidade do
ambiente. Selecionar Base/Free explicitamente no plano futuro (`aks_sku_tier`
já existe); não confundir com AKS Automatic, cujo tier é Standard. A ausência
de SLA financeiro é compatível com este laboratório. Standard só tem sentido se
um requisito identificado o justificar dentro do orçamento.

A documentação de system pools consultada em 2026-09-27 lista pelo menos dois nós,
SKU de pelo menos quatro vCPUs/4 GB e exclui série B. Confirmar requisitos e
suporte da combinação na descoberta; a validação local rejeita
`node_count=1`, sem substituir a aceitação real pelo serviço. Compartilhar o pool de sistema com a aplicação
é uma concessão de laboratório a justificar, não uma topologia de produção.
Quota e catálogo não garantem capacidade disponível no momento da criação.

A estimativa inclui nós e discos de SO, PVCs e snapshots se previstos, ACR,
Load Balancer/IP, tráfego/egress, backend Terraform e eventual telemetria. Distinguir
custo **ativo**, **cluster parado** e **retenção após remoção**; anotar moeda, região,
data, preços da oferta, tributos/conversão aplicáveis e horas/dias. Preço público
é referência, não confirmação da tarifa contratada. Não tratar crédito como
saldo confirmado ou descontá-lo do teto sem evidência.

Antes da janela, registrar como consultar consumo e alertas de orçamento, além
de calcular localmente duração × tarifa e custos retidos: Cost Management pode
ter atraso e budget não desliga recursos. A contingência aprovada no registro
privado cobre encerramento e incerteza, não novos ensaios. Resumir a viabilidade no RELEASE_PLAN, guardando
respostas completas sensíveis fora do Git; não criar outro diário duplicado.

CLI/Terraform são preferidos para descoberta técnica, validação, implantação e
inventário. Portal complementa confirmação de oferta/cobrança, pagamento, MFA e
capturas úteis. Login e decisões de conta pertencem ao operador. A branch nova não
corresponde ao subject OIDC de `main`: operação local autorizada ou uma revisão
explícita da federação devem resolver isso antes do deploy, sem abrir a confiança.

## Isolamento da preparação Azure

| Local | Responsabilidade |
| --- | --- |
| `config/aks-portability.json` | Candidata pública, sem IDs de conta, autorização financeira ou quota específica da assinatura |
| `k8s/overlays/aks-portability/` | Adaptação AKS em três fases; renderização com imagens imutáveis e entradas privadas pelo preparador |
| `infra/bootstrap/` e `infra/environment/` | Roots Azure existentes; não criar uma segunda árvore Terraform |
| `scripts/azure/` | Procedimentos Azure e revisão offline; smoke HTTP genérico continua compartilhado |
| Área privada e `artifacts/azure-*` ignorados | Backend concreto, plans/state, credenciais, autorização e respostas da assinatura |

`config/environment.json` conserva exatamente o registro da v1.2.0-rc.1; não é
fonte da candidata Azure. A descoberta de quotas está no histórico vinculado pelo plano; originais permanecem locais.
Nenhuma config pública contém IDs reais de assinatura/tenant ou caminhos pessoais.
Os tamanhos, ranges e patch da candidata continuam sujeitos a aprovação final.

O overlay usa manifests existentes sem alterar `k8s/base` ou `kind-local`.
As guardas `validation-only`, `deployment-blocked` e o nodeSelector impossível
continuam presentes até preparar uma configuração concreta aprovada, com digest.
Alterações da base durante v1.3 devem ser evitadas; se indispensáveis e neutras
quanto ao provedor, exigem justificativa e revisão explícita do impacto no Kind.

```powershell
python scripts/azure/check_kind_regression.py --output artifacts/kind-regression.json
```

A CI compara foundations, migrations e runtime renderizados com o commit fixo
`777900da060419acf559dec56902ef1e326504cf` da v1.2.0-rc.1. Usa kubectl/Kustomize
fixados pela referência; normaliza somente CRLF/LF e falha em qualquer diferença.
Não executa checkout, aplica manifests ou acessa clusters. Uma diferença legítima
exige decisão explícita sobre a guarda, não atualizar automaticamente o baseline.
Igualdade de render não demonstra equivalência de runtime nem isola causalidade
entre ambientes. A CI precisa do commit histórico; checkout obtém o histórico.

A convenção de state usa conta/container próprios e duas keys por implantação:
`aks-portability/<window-id>/bootstrap.tfstate` e
`aks-portability/<window-id>/environment.tfstate`. Os nomes concretos ficam fora
do Git. Não há migração de state existente nesta preparação; `backend.hcl.example`
continua sintético. A criação de novos destinos depende da janela aprovada.

## Candidata e sequência de aceite

`environment/brazilsouth.candidate.tfvars.example` fixa apenas os candidatos
não privados identificados na descoberta. IDs, nomes e origem de rede continuam
sintéticos; o arquivo não é carregado automaticamente. Aprovação permanece falsa.
Não executar um plan Azure com esse exemplo nem promover o arquivo a aprovação.

| Fase futura | Verificação e evidência exigidas antes de avançar |
| --- | --- |
| Pré-janela | Quotas regional/Dsv6 livres para 12 vCPUs; versão/SKU/Ubuntu Gen2 e discos compatíveis; IP do executor; estimativa final e encerramento aprovados |
| Backend e IAM | State protegido e cópia verificada; Entra data-plane do Blob e administração Kubernetes autorizados; federação de main preservada |
| Imagem/ACR | Proveniência do commit congelado e imagem amd64; digest real após publicação; modo RBAC conferido e pull do kubelet demonstrado |
| Foundations/runtime | PVCs novos; migrações e seed antes do runtime; requests e sistema cabendo na capacidade alocável por nó |
| Fluxo funcional | Evento sintético identificado: admissão, conclusão Tracking/Order e Notifications; readiness ou HTTP 202 não encerram o aceite |
| Persistência | Registrar identidade/resultado antes, recriar somente o pod de banco previsto, confirmar mesmo PVC e resultado depois; não alegar backup ou HA |
| Rede | Sonda permitida e sonda negada para o mesmo destino pronto, com timeout limitado; registrar configuração e efeito, sem abrir políticas como atalho |
| Encerramento | Exportar evidências sanitizadas e cópias necessárias; inventariar recursos, planos e custos; conferir remoção e retenção por ID |

Essa sequência é um procedimento, não um orquestrador público integral.
Os auxiliares exigem contexto AKS explícito,
sem ações de Docker/Kind ou acesso a volumes históricos. Cada ensaio usa destino
novo e termina no primeiro impedimento relevante, preservando evidências.

**Retenção curta:** stop pode atender a uma pausa no mesmo dia; não é a estratégia
padrão para vários dias. Após a captura, o plano de remoção deve separar cluster,
atribuições dependentes, recursos gerenciados de nós e discos Retain remanescentes,
preservando deliberadamente ACR/backend pelo prazo aprovado. Não executar destroy
genérico nem apagar manualmente recursos para fugir de `prevent_destroy`.
A revisão deve manter coerência com o state. O plano seletivo da janela foi
aplicado; a remoção dos recursos retidos ainda requer revisão própria. Antes de nova criação ou rotação de pool, recalcular quota e custo.

## Fechamento da primeira janela: decisões e procedimento

A execução proposta é local, pelo operador autenticado, com acesso temporário e
explicitamente aprovado. A federação GitHub de main permanece intacta. Antes de
qualquer apply, conferir o plano real, inclusive as atribuições que ele cria.
Os privilégios ARM observados não comprovam acesso ao Blob ou à API Kubernetes.

| Necessidade | Escopo delimitado; conferir concessão e remoção por janela |
| --- | --- |
| Criar/verificar container e state com Entra | Storage Blob Data Contributor na conta dedicada do backend durante bootstrap; revisar acesso de rotina ao container depois |
| Publicar imagens sem senha administrativa | AcrPush no registry dedicado, somente se o acesso efetivo atual não bastar e o modo for RBAC |
| Namespace, StorageClasses e policies iniciais | Azure Kubernetes Service RBAC Cluster Admin no cluster dedicado para o operador, com remoção/revisão após bootstrap |
| Deploy de rotina | Roles já declaradas no Terraform para a identidade de deploy; não ampliar a federação para a branch por conveniência |

Essas atribuições são propostas de preparação, não autorização. Os roots agora
possuem `grant_operator_access=false` e `operator_object_id=null` por padrão;
nenhuma identidade é inferida do login. Ativar a opção requer aprovação do usuário,
escopo e prazo. O ambiente inclui também Cluster User para obter kubeconfig normal,
sem `--admin`; RBAC Cluster Admin é o papel separado para o data-plane Kubernetes.

No bootstrap, a dependência conta → role Blob → container está declarada. A
propagação de RBAC não é instantânea; se a criação do container falhar por acesso,
parar e conferir propagação/identidade/firewall antes de retomar o mesmo state.
Não habilitar Shared Key nem repetir automaticamente um apply inteiro. O operador
de state conserva acesso enquanto os states retidos precisarem ser administrados;
revogar só após garantir acesso substituto e cópia independente.

O smoke existente `scripts/verify_flow.py` usa somente HTTP e pode operar por
port-forward autenticado. Reutilizá-lo com dados sintéticos novos e referência
congelada; não portar os executores de escala/Kind. Credenciais ficam no ambiente
privado, nunca em argumentos ou JSONs públicos. A identidade da imagem é verificada
separadamente pelo digest do deployment e imageID do pod.

### Revisão offline da remoção

O utilitário `scripts/azure/review_removal.py` compara um JSON obtido por
`terraform show -json` de um plano salvo com um inventário privado previamente
revisado. Cada entrada de `delete` contém `address`, `type` e `id` ARM completos.
Somente cluster, roles, federação e identidade dedicada são tipos elegíveis; ACR,
grupos e backend não podem ser incluídos na lista. O verificador rejeita criação,
update, replacement, drift, plano incompleto, exclusões extras ou ausentes.
Ele não chama Azure, Terraform ou kubectl e nunca autoriza a execução.

```powershell
python scripts/azure/review_removal.py --plan artifacts/azure-window/removal-plan.json --plan-binary artifacts/azure-window/removal.tfplan --inventory artifacts/azure-window/removal-inventory.json --output artifacts/azure-window/removal-review.json
```

Arquivos de entrada são privados: planos podem conter segredos mesmo quando a
saída do verificador não os expõe. O resultado preserva hashes do JSON e do binário, contagem e
limites. Ele não comprova que o JSON foi derivado daquele binário: produzir o JSON
com `terraform show -json` imediatamente antes da revisão e conservar ambos privados.
Conferir também o hash do plano binário efetivamente aplicado; revisar
novamente se o plano mudar. Não usar a aprovação de um JSON para outro binário.

Ainda é necessário gerar o plano concreto de encerramento depois de conhecer os
IDs reais, sem executar destruição genérica do root protegido. A geração de plano
seletivo de destruição, se adotada, é exceção revisada com todos os dependentes;
não é recomendação de target para deploy normal. Não apagar declarações,
`prevent_destroy` ou state como atalho. Após remoção, reconciliar por leitura o
state e o inventário; um novo apply do mesmo root pode recriar o cluster.

A receita de plano seletivo fica delimitada aos endereços abaixo, depois de
conferir o state real. `operator_push`, ACR, RG e backend ficam fora da seleção.
O JSON privado de inventário é preenchido com os IDs lidos no state e confrontado
com o ARM; não presumir que nome igual significa recurso igual. Nenhum comando
abaixo deve ser executado antes da janela autorizada e da exportação prevista.

```powershell
$RemovalTargets = @(
  '-target=azurerm_kubernetes_cluster.runtime',
  '-target=azurerm_role_assignment.kubelet_pull',
  '-target=azurerm_role_assignment.deployment_cluster_user',
  '-target=azurerm_role_assignment.deployment_namespace_writer',
  '-target=azurerm_role_assignment.operator_cluster_user',
  '-target=azurerm_role_assignment.operator_cluster_admin',
  '-target=azurerm_federated_identity_credential.github_main',
  '-target=azurerm_user_assigned_identity.deployment'
)
& $Terraform '-chdir=infra/environment' plan -destroy -input=false -lock-timeout=60s "-var-file=$PrivateVariables" "-out=$PrivateRemovalPlan" @RemovalTargets
if ($LASTEXITCODE -ne 0) { throw 'Removal plan failed; preserve state and review.' }
& $Terraform '-chdir=infra/environment' show -json $PrivateRemovalPlan | Set-Content -LiteralPath $PrivateRemovalJson -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Plan export failed; do not apply.' }
```

Revisar essa saída pelo utilitário, por leitura humana e pelo inventário dos
recursos gerenciados não representados no state. Aplicar somente o binário revisado,
com autorização de remoção específica; não trocar por `terraform destroy` e não
recalcular automaticamente outro plano ao executar. Os testes offline do revisor
cobrem identidade, drift e exclusões extras; não afirmam que esse plano real já
foi gerado ou que a remoção de um serviço Azure foi ensaiada.

**Limite importante:** excluir o cluster pode remover recursos do grupo gerenciado,
inclusive discos que se pretendia preservar. `Retain` do PV não protege contra
exclusão de recursos Azure. Preservar e conferir cópias necessárias antes da remoção;
o verificador de planos não enxerga exclusões implícitas do serviço nem comprova
backup. Conferir discos, IPs, Load Balancer e custos residuais separadamente.

## Proposta de janela funcional e prontidão

**Proposta para revisão, sem autorização de execução:** até seis horas desde a
criação do primeiro recurso cobrado, reservando a última hora para exportação e
encerramento. Não começar um novo cenário após cinco horas. Se uma etapa falhar,
classificar e preservar a tentativa; não iniciar reconstruções automáticas.

| Recurso/fase | Proposta e limite |
| --- | --- |
| Backend | RG próprio, StorageV2 Standard LRS, container privado; primeiro recurso potencialmente cobrado é a conta Storage |
| Ambiente | RG próprio, ACR Basic, AKS Free, dois D4s_v6, Ubuntu, versão candidata 1.34.11, discos de SO gerenciados de 64 GiB sujeitos à compatibilidade |
| Gerenciados pelo AKS | Grupo de nós, VMSS, rede, Load Balancer/IP e discos; inventariar IDs e custos, não presumir que constam individualmente no state |
| Workload | PVCs novos StandardSSD_LRS de 32/16 GiB; uma réplica por processo, requests originais sem importar tuning Kind |
| Segurança preparada | Role Blob opcional no backend; três roles opcionais do operador no ambiente; três roles existentes de kubelet/deploy, identidade gerenciada e federação main |
| Retenção proposta | Remover execução ao fim da janela; ACR/backend por até sete dias para revisão, com custo e remoção final explicitamente aprovados |

O render soma 5,5 CPU e 5376 MiB de requests de foundations+runtime, sem os
componentes do sistema. Migrações sequenciais acrescentam 0,5 CPU/384 MiB antes do
runtime. Isso não comprova agendamento: conferir allocatable, DaemonSets e encaixe
por nó antes do aceite. Não reduzir requests ou ampliar nós automaticamente.

### Imagens e geração local

A imagem local `fulfillflow-kind-runtime:source-9e3a135a00db` foi encontrada como
Linux/amd64. O ID local foi conferido contra o
[preflight publicado de capacidade](../docs/evidence/scaling/environment-preflight.json):
`sha256:582a858debe2ff64d481e810b2d5ae5a1aba6a669516bca36a15eb12e77ec072`,
associado ao commit `9e3a135`. Isso identifica a imagem preservada da avaliação,
sem alegar novo build reproduzido ou auditoria de supply chain. Publicar essa
imagem preservada, sem reconstrução silenciosa. PostgreSQL e RabbitMQ têm
origens fixadas por digest na base; importar/publicar no ACR e capturar os digests
resolvidos lá. Não confundir image ID local, índice multiarch e manifest de plataforma.

`prepare_manifests.py` exige mapa JSON de cada imagem de origem para destino ACR
com digest não placeholder. O ensaio local usa exclusivamente fixtures sintéticas;
essas fixtures nunca são entradas de deploy. A geração retira somente as guardas
conhecidas da candidata, preserva recursos/contratos e recusa imagens não mapeadas.
Ela não consulta registry, não atesta proveniência e não aplica manifests.

```powershell
python scripts/azure/prepare_manifests.py --images $PrivateImageMap --registry $AcrLoginServer --window $WindowId --kubectl .tools/kubectl/kubectl.exe --output $NewManifestDirectory
```

Secrets novos continuam fora do Git, em diretório com ACL do operador. Reutilizar
o contrato do guia Kubernetes e o helper de definitions; injetar por stdin, com
kubeconfig/contexto AKS exclusivos. Não copiar secrets Kind nem imprimir credenciais.
A sequência operacional segue namespace/guardas → secrets → foundations → migrations
sequenciais → runtime → túnel HTTP loopback → smoke, nunca apply do agregado.

### Verificações preparadas e limites restantes

- **Funcional:** `scripts/verify_flow.py` já implementa aceite por evento e duplicata
  intencional. Conservar seu JSONL e IDs; uma nova execução cria novo evento, não
  serve como verificação de persistência do anterior.
- **Persistência:** capturar cluster, pod UID, PVC UID, PV UID, volumeHandle/CSI e
  estados/IDs funcionais antes/depois da recriação de `postgres-0`. O revisor
  `scripts/azure/review_persistence.py` exige pod diferente, mesmo volume e mesmo
  resultado. A coleta deve preservar respostas originais e origem de cada campo;
  preencher resumos manualmente não substitui evidência. Recriar só com contexto,
  UID alvo e ownership da janela conferidos; não excluir PVC/PV.
- **Rede:** a geração opcional `--postgres-pod-ip` e `--probe-image` produz Jobs
  permitidos/negados contra o mesmo pod PostgreSQL pronto, sem credenciais e sem
  retries. O Service é headless. Exigir sucesso permitido antes/depois da sonda
  negada e IP/UID estáveis; timeout negado é candidato a bloqueio, não prova isolada.
  Conexão recusada, pod não iniciado, perda do alvo ou erro de coleta são inconclusivos.
- **Encerramento:** conferir plano/IDs, exportar cópias e evidências antes da
  remoção; o revisor offline não executa teardown nem vê exclusões implícitas AKS.
  Preservar inventário final de recursos retidos e data de remoção acordada.

O procedimento continua composto por etapas explícitas, sem executor que faça
apply/retry/destroy automaticamente. Os coletores de persistência e inventário
estão implementados; os testes de persistência usam fixtures, pois não existe AKS.
A consulta real de inventário foi ensaiada sem mutações. Antes da autorização final,
aprovar os parâmetros privados, os planos reais e a estimativa reunidos na
revisão final. Dump completo dos dados sintéticos não é requisito normal;
falha inesperada interrompe a remoção para decisão específica. IDs/digests produzidos pelo serviço só podem ser
preenchidos e conferidos durante a execução; não inventá-los antecipadamente.

### Coleta delimitada, sem mutações

`capture_persistence.py` aceita um JSON privado de alvo contendo `window`,
`cluster_id` ARM, `api_server`, `system_namespace_uid`, `order_id`, `shipment_id`,
`event_id` (UUID do TrackingEvent, não o external_event_id) e `notification_id`.
Os quatro IDs de negócio vêm do smoke concluído. O endpoint/UID kube-system vêm
na primeira conexão ao AKS identificado pelo ARM; não copiar de outro cluster.
O coletor confere contexto, UID, label da janela, pod Ready e vínculo PVC/PV/CSI.
Ele abre seu próprio port-forward loopback para Core e faz quatro GETs sem retries,
sem segredo de webhook. Reconfere a infraestrutura ao final e encerra apenas seu
próprio túnel. Não substitui o teste de NetworkPolicy, pois usa port-forward.

```powershell
python scripts/azure/capture_persistence.py --target $PrivateTarget --kubectl $Kubectl --kubeconfig $PrivateKubeconfig --context $Context --output $BeforeCapture
# Depois da recriação autorizada e comprovada de postgres-0, usar destino novo:
python scripts/azure/capture_persistence.py --target $PrivateTarget --kubectl $Kubectl --kubeconfig $PrivateKubeconfig --context $Context --output $AfterCapture
python scripts/azure/review_persistence.py --before "$BeforeCapture/capture.json" --after "$AfterCapture/capture.json" --output $PersistenceReview
python scripts/azure/capture_inventory.py --az $AzureCli --subscription $SubscriptionId --output $NewPrivateInventory
```

Esses comandos são para a janela autorizada, não para execução agora. O coletor
não recria o pod. A captura guarda projeções selecionadas, paths/status/horários e
hashes das respostas HTTP, não os payloads integrais nem uma fotografia atômica.
Falha de consulta ou mudança de pod/volume durante a captura impede o aceite.
Os arquivos incluem identificadores operacionais e permanecem privados até sanitização.

O inventário usa GET paginado com assinatura explícita; rejeita paginação fora do
escopo e IDs duplicados/incompatíveis. Comparar antes/depois por ID, incluindo o
grupo gerenciado pelo AKS. Ausência no inventário ARM não comprova custo zero nem
cobre todo recurso filho: conferir exclusão concluída, discos/IPs e cobrança residual.

### Cliente local e compatibilidade da candidata

O cliente local foi instalado somente em `.tools/kubelogin-v0.2.20/`, ignorado;
não houve alteração global de PATH ou conversão de kubeconfig. Fonte oficial:
[kubelogin v0.2.20](https://github.com/Azure/kubelogin/releases/tag/v0.2.20).
SHA-256 do ZIP win-amd64:
`e26d5ce8a48e9b6ac53fd93cf45a1eec050f859ccca3654beb4887decd8dee33`.
SHA-256 do executável verificado:
`4f3d62b3940ae58fd1af44facb2ca062757a2ccc9f46c94826af81d5b88bc406`.
O `--version` confirmou a referência. Durante a janela, usar autenticação Azure CLI
no kubeconfig exclusivo, com o cliente disponível apenas no PATH do processo;
nunca `az aks get-credentials --admin`. O teste local não comprova acesso Kubernetes.
[Autenticação kubelogin](https://learn.microsoft.com/en-us/azure/aks/kubelogin-authentication).

A documentação lista Ubuntu 22.04 como padrão de `Ubuntu` no Kubernetes 1.34 e
como compatível com NVMe Gen2. Isso sustenta a candidata, mas não valida alocação
AKS/VM/disco em Brazil South. Preservar a imagem efetiva do nó, versão do SO e
configuração do disco retornados pelo serviço; incompatibilidade encerra a etapa,
sem trocar versão/SKU silenciosamente.
[OS no AKS](https://learn.microsoft.com/en-us/azure/aks/upgrade-os-version),
[NVMe](https://learn.microsoft.com/en-us/azure/virtual-machines/enable-nvme-interface).

## Validação local

Executar na raiz do repositório com as versões fixadas disponíveis no PATH:

```powershell
terraform fmt -check -recursive infra
terraform -chdir=infra/bootstrap init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/bootstrap validate
terraform -chdir=infra/bootstrap test
terraform -chdir=infra/environment init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/environment validate
terraform -chdir=infra/environment test
```

`init -backend=false` instala/verifica o provider e não conecta ao backend.
Os testes usam exclusivamente `mock_provider` e `command = plan`: verificam
entradas e estrutura proposta, incluindo rejeição de origem aberta/inválida,
guardas de aprovação e escopos da identidade de deploy. O provider fixado expõe
`kubelet_identity` como bloco calculado/opcional que esses mocks não preenchem.
Por isso, os testes de ambiente selecionam alvos e excluem a atribuição `AcrPull`;
o aviso de targeting é esperado **somente nos testes**, não é orientação para
operação. A ligação do kubelet é revisada no código/schema e requer verificação
remota futura. Os testes não verificam Azure, custo, quota, autenticação,
autorização, locking, disponibilidade ou conectividade.
Para atualizar locks após mudança autorizada de versão, usar `providers lock
-platform=windows_amd64 -platform=linux_amd64` em cada root; não editar hashes.

## Configuração de referência

- AKS com API **pública restrita** a uma lista obrigatória de IPv4 `/32` válidos.
  Não é cluster privado. Selecionar executor com egress público estável e aprovado;
  o runner hospedado padrão do GitHub não tem essa condição implicitamente.
- Nós Linux com contagem, VM, disco de SO e versão Kubernetes explícitos. Sem
  autoscaler, upgrade automático do Kubernetes ou imagem do SO; correções futuras
  exigem operação revisada. Upgrade do pool reserva um nó adicional (`max_surge=1`),
  que entra em quotas e estimativa. VM/plataforma amd64 e a imagem Ubuntu escolhida
  pelo AKS para a versão exata devem ser verificadas e registradas antes de aprovação.
  Sem atualizações automáticas, limitar a janela funcional e revisar patches antes
  de qualquer extensão da operação; não assumir manutenção indefinida.
- Azure CNI Overlay com Cilium, load balancer Standard e um IP de saída gerenciado.
  São recursos cobrados/incluídos na estimativa. Confirmar que ranges de pods,
  serviços, rede de nós e redes conectadas não se sobrepõem. O motor suporta as
  NetworkPolicies, mas somente sua aplicação e ensaio comprovam isolamento.
- ACR autenticado, sem admin ou pull anônimo. Seu endpoint de rede permanece
  público; não há Private Link. `prevent_destroy` protege registry e grupo no
  Terraform enquanto as declarações persistirem. Não há limpeza automática de
  manifests; conservar digests/evidências requer política operacional e orçamento.
- O provider 4.55.0 não expõe `role_assignment_mode`. O root parte do modo RBAC
  de criação e concede `AcrPull` apenas à identidade kubelet neste ACR. Antes de
  publicação/pull, verificar por leitura o modo efetivo **RBAC Registry Permissions**.
  Se estiver ABAC, interromper e revisar a configuração; não presumir que `AcrPull`
  se aplica. O teste local não comprova o modo remoto.

## Identidades e responsabilidades

O AKS usa identidade gerenciada, Entra e Azure RBAC, com contas locais e
`run-command` desabilitados. Não há output de kubeconfig. State/plan ainda podem
conter material sensível do provider e devem receber a proteção indicada abaixo.

O root de ambiente propõe três atribuições, executáveis somente por um operador
de provisionamento previamente autorizado: `AcrPull` da identidade kubelet no ACR;
`Azure Kubernetes Service Cluster User Role` da identidade de deploy no cluster;
`Azure Kubernetes Service RBAC Writer` dessa identidade em
`<cluster-id>/namespaces/fulfillflow`. Por padrão não atribui role ao solicitante e não concede
Owner, Contributor de assinatura, acesso ao backend ou push de imagens ao deploy.

A identidade de deploy usa OIDC com issuer GitHub, audiência
`api://AzureADTokenExchange` e subject exato
`repo:campos-labs/fulfillflow-infra:ref:refs/heads/main`. Pull requests e outros
repositórios/branches não correspondem a essa confiança. O workflow futuro precisa
ser explícito e limitar concorrência, com controle de quem altera workflows e
código confiável. Um job com GitHub Environment
altera o subject padrão: revisar conjuntamente a federação antes de adotá-lo.

O Writer pode ler/escrever Secrets e executar pods como ServiceAccounts do
namespace. Não colocar ServiceAccounts privilegiadas nesse namespace. Namespace,
StorageClasses, policies que exigem privilégios superiores e RBAC inicial ficam
com o administrador Entra identificado e autorizado para a janela. A identidade de deploy não cria esses recursos cluster-wide.
Jobs de migração e runtime do namespace usam o fluxo de implantação posterior.
Não criar credencial administrativa de pipeline para compensar acesso ausente.

## Backend e migração do state

O bootstrap começa intencionalmente com **state local sensível**, pois o backend
não existe em uma implantação nova. O grupo é separado do ambiente removível. Storage usa TLS 1.2,
Shared Key desabilitado, Entra, container privado, firewall com deny padrão e sem
bypass, versionamento e retenção de exclusão explícita. A lista de egress contém
endereços IPv4 individuais (Storage não aceita a notação `/32`). Verificar IPs
públicos reais e acesso pelo executor; as regras não garantem acesso de serviços
Azure da mesma região. A conectividade concreta permanece pré-condição.

A role de dados opcional do bootstrap permanece desabilitada por padrão. A administração
precisa autorizar acesso de dados Entra para os operadores do state e seu escopo;
Contributor no ARM não substitui `Storage Blob Data Contributor`. Acesso temporário
necessário para criar/verificar o backend e o acesso de rotina ao container devem
ser resolvidos antes da operação, sem grants amplos como atalho.

Sequência de bootstrap; a primeira execução e seus limites estão no relatório:

1. Aprovar alvo, custos/retenção, permissões e janela de bootstrap. Registrar os
   providers Azure já habilitados; os roots não fazem registro automático. Criar
   área local com acesso restrito e cópia independente protegida para state/plan.
2. Executar e revisar o plano do bootstrap com identidade individual autorizada;
   aplicar somente após a autorização correspondente. Preservar os arquivos
   locais `terraform.tfstate` e `.backup` como dados sensíveis, fora do Git.
3. Conferir outputs de conta/container/grupo, firewall e acesso Entra. Criar uma
   cópia ignorada de `backend.hcl.example` com esses identificadores; o bootstrap
   usa a key **`aks-portability/<window-id>/bootstrap.tfstate`**, o ambiente usa
   **`aks-portability/<window-id>/environment.tfstate`**. A conta/container são
   exclusivos desta implantação; não reutilizar backend/state histórico. O
   identificador da janela permanece estável em retomadas da mesma implantação.
   Não passar access key, SAS ou segredo de cliente.
4. Copiar `bootstrap/backend.tf.example` para `bootstrap/backend.tf`. Com a cópia
   local protegida e a identidade correta, executar no bootstrap
   `terraform init -migrate-state -backend-config=backend.hcl` apontando para o
   arquivo preparado. Não usar `-force-copy` nem apagar o state local antes de
   conferir migração, lineage, serial, leitura remota e cópia independente.
5. Conferir locking por lease do Blob em uma verificação controlada, sem operações
   concorrentes de aplicação. Inicializar o root de ambiente com sua key própria,
   sem `-migrate-state` se ele ainda não possuir state. O backend remoto não é
   comprovado apenas pelo sucesso de `init -backend=false` ou pelos mocks.

Durante a operação, usar locking e timeout explícito; interromper no primeiro
erro, conservar diagnóstico sanitizado e classificar antes de retomar. Não apagar
leases nem forçar unlock sem confirmar ausência do proprietário ativo.

`prevent_destroy` existe em grupo/conta/container do backend e grupo/ACR do ambiente.
Não é backup nem Azure Resource Lock e deixa de proteger uma declaração removida.
Uma destruição genérica do root de ambiente será bloqueada para preservar imagens.
Encerramento requer plano separado que preserve backend, ACR e evidências, exporte
e verifique dados necessários e detalhe recursos/custos remanescentes. Retenção
mantém cobrança; remover o AKS ou PVCs não comprova restauração.

Para uma janela curta, preparar captura e encerramento antes de iniciar cobrança.
Parar apenas deployments/pods não desaloca nós. `az aks stop` é uma possibilidade
para cluster VMSS compatível, sujeita às restrições do serviço; confirmar estado
Stopped/deallocated e inventário posterior. A retomada pode falhar por capacidade
da região. ACR, discos, IPs, backend e telemetria retidos precisam de conferência
própria, mesmo após stop ou remoção do cluster.

Definir prazo final de retenção e custo até essa data; não deixar ACR/backend
indefinidamente por estarem protegidos. Antes de remover qualquer recurso
persistente, conferir evidências exportadas e cópias necessárias. A remoção final
exige plano específico, com tratamento explícito de `prevent_destroy`. Não
contornar proteções por destruição genérica, perda de state ou remoção de volumes
antes dessas conferências. Custos ainda não consolidados permanecem estimados e
identificados no fechamento.

## Referências de schema e comportamento

- [AKS no AzureRM 4.55.0](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.55.0/website/docs/r/kubernetes_cluster.html.markdown)
- [ACR no AzureRM 4.55.0](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.55.0/website/docs/r/container_registry.html.markdown)
- [Storage no AzureRM 4.55.0](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.55.0/website/docs/r/storage_account.html.markdown)
- [Backend Azure Blob e autenticação Entra](https://developer.hashicorp.com/terraform/language/backend/azurerm)
- [Azure CNI e NetworkPolicies](https://learn.microsoft.com/en-us/azure/aks/use-network-policies)
- [Azure RBAC no AKS e escopo de namespace](https://learn.microsoft.com/en-us/azure/aks/entra-id-authorization)
- [Tiers de gerenciamento AKS: Free, Standard e Premium](https://learn.microsoft.com/en-us/azure/aks/free-standard-pricing-tiers)
- [Requisitos dos system node pools](https://learn.microsoft.com/en-us/azure/aks/use-system-pools)
- [Parada e retomada do AKS](https://learn.microsoft.com/en-us/azure/aks/start-stop-cluster)
- [Budgets e limites das notificações](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets)
- [API pública de preços de referência](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
- [Integração AKS/OTLP com Azure Monitor (preview)](https://learn.microsoft.com/en-us/azure/azure-monitor/containers/kubernetes-open-protocol)
