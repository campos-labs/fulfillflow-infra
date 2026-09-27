# Terraform — preparação da portabilidade Azure

Esta configuração de referência não foi implantada e não é necessária para a
entrega em Kind. O incremento `feature/v1.3-aks-portability` prepara AKS e ACR na
mesma nova assinatura paga, sem uso da Student. O [RELEASE_PLAN](../RELEASE_PLAN.md#4-portabilidade-para-aks)
registra etapas, critérios de custo e pausas; o [DESIGN](../DESIGN.md#89-verificação-de-portabilidade-para-aks)
define o aceite. Nenhuma consulta autenticada à nova assinatura foi realizada nesta
preparação documental.

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
criação de recursos. [config/environment.json](../config/environment.json) mantém
somente requisitos públicos de preparação, sem valores de autorização.
O registro privado da janela pode ficar fora do checkout ou em arquivo local
com exclusão do Git conferida; não copiá-lo para logs, CI ou pacotes publicados.
Ainda faltam alvo, configuração, estimativa e autorização do procedimento.

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
suporte da combinação na descoberta; não assumir que exemplos/testes que aceitam
`node_count=1` comprovam viabilidade. Compartilhar o pool de sistema com a aplicação
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
`<cluster-id>/namespaces/fulfillflow`. Não atribui role ao solicitante e não concede
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
com o administrador Entra autorizado, cuja identificação/escopo ainda precisam
ser decididos. A identidade de deploy não cria esses recursos cluster-wide.
Jobs de migração e runtime do namespace usam o fluxo de implantação posterior.
Não criar credencial administrativa de pipeline para compensar acesso ausente.

## Backend e migração futura

O bootstrap começa intencionalmente com **state local sensível**, pois o backend
ainda não existe. O grupo é separado do ambiente removível. Storage usa TLS 1.2,
Shared Key desabilitado, Entra, container privado, firewall com deny padrão e sem
bypass, versionamento e retenção de exclusão explícita. A lista de egress contém
endereços IPv4 individuais (Storage não aceita a notação `/32`). Verificar IPs
públicos reais e acesso pelo executor; as regras não garantem acesso de serviços
Azure da mesma região. A conectividade concreta permanece pré-condição.

Não há atribuição automática de role de dados no bootstrap. A administração
precisa autorizar acesso de dados Entra para os operadores do state e seu escopo;
Contributor no ARM não substitui `Storage Blob Data Contributor`. Acesso temporário
necessário para criar/verificar o backend e o acesso de rotina ao container devem
ser resolvidos antes da operação, sem grants amplos como atalho.

Sequência de bootstrap para eventual implantação, **ainda não executada**:

1. Aprovar alvo, custos/retenção, permissões e janela de bootstrap. Registrar os
   providers Azure já habilitados; os roots não fazem registro automático. Criar
   área local com acesso restrito e cópia independente protegida para state/plan.
2. Executar e revisar o plano do bootstrap com identidade individual autorizada;
   aplicar somente após a autorização correspondente. Preservar os arquivos
   locais `terraform.tfstate` e `.backup` como dados sensíveis, fora do Git.
3. Conferir outputs de conta/container/grupo, firewall e acesso Entra. Criar uma
   cópia ignorada de `backend.hcl.example` com esses identificadores; o bootstrap
   usa a key **`bootstrap.tfstate`**, o ambiente usa **`environment.tfstate`**.
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
