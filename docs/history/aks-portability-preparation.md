# Preparação e intervenções da verificação AKS

Este registro resume a evolução técnica; método e resultados estão no
[relatório](../AKS_PORTABILITY_EVALUATION.md). As autorizações e entradas da
assinatura permanecem privadas e não são reutilizáveis.

- Descoberta de regiões, SKUs, providers e quotas; configuração escolhida em
  Brazil South, dois D4s_v6, AKS Free e ACR Basic.
- Configuração/overlay AKS isolados e render Kind comparado com `v1.2.0-rc.1`.
  Roots Terraform com state exclusivo; imagens identificadas por digest.
- Implantação, migrations e smoke funcional confirmados.
- Primeira captura após recriação do pod PostgreSQL incompleta. A continuação
  verificou o mesmo volume e resultado após stop/start, sem nova recriação;
  essa intervenção limita a interpretação causal.
- Probes de rede permitido → bloqueado → permitido concluídos.
- Primeira extensão HTTP recusada por requests de CPU insuficientes. O diagnóstico
  isolado posterior suspendeu três workers após ausência de pendências, confirmou
  uma consulta saudável e quatro spans, removeu clones e restaurou os workers.
- Encerramento seletivo com inventário e evidências preservados. Nenhuma falha
  HTTP foi injetada no AKS; não houve Azure Monitor ou campanha de escala na nuvem.

Os registros de tentativas permanecem nos [pacotes](../evidence/aks-portability/README.md).
O histórico completo de execução permanece local; este resumo não o substitui por
uma alegação de sucesso contínuo nem disponibiliza entradas privadas.
