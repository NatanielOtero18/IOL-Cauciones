# caucion-alert

Lambda que consulta las cauciones en la API de IOL cada minuto (lun a vie, 11 a 17 h, hora Argentina) y avius por Telegram si alguna supera un umbral de TNA.

```
EventBridge Scheduler (cron, TZ Argentina)
   └─> Lambda (python3.12, sin dependencias)
         ├─> SSM Parameter Store (credenciales IOL y Telegram)
         ├─> API IOL (token + cauciones)
         └─> Telegram (aviso)
```

## 1. Cargar los secretos (fuera de Terraform)

Los secretos no van en Terraform para que no queden en el state.

```bash
aws ssm put-parameter --region us-east-1 --type SecureString --name /caucion-alert/iol_user --value 'TU_USUARIO'
aws ssm put-parameter --region us-east-1 --type SecureString --name /caucion-alert/iol_pass --value 'TU_PASSWORD'
aws ssm put-parameter --region us-east-1 --type SecureString --name /caucion-alert/tg_token --value 'TOKEN_DEL_BOT'
aws ssm put-parameter --region us-east-1 --type SecureString --name /caucion-alert/tg_chat  --value 'TU_CHAT_ID'
```

## 2. Desplegar

```bash
cp terraform.tfvars.example terraform.tfvars   # editar
terraform init
terraform plan
terraform apply
```

## 3. Probar

```bash
aws lambda invoke --region us-east-1 --function-name caucion-alert \
  --payload '{"debug": true}' --cli-binary-format raw-in-base64-out out.json
cat out.json
aws logs tail /aws/lambda/caucion-alert --region us-east-1 --since 5m
```

Con `{"debug": true}` la respuesta cruda de IOL queda en los logs, para confirmar en qué campo viene la taus (`extraer_tauss`).

## Costo

~22 días × 360 invocaciones ≈ 8.000 por mes, 128 MB, menos de 1 s cada una: dentro de la capa gratuita de Lambda. SSM Parameter Store estándar y EventBridge Scheduler a este volumen también son gratis. Logs con retención de 14 días.

## Notas

- `reserved_concurrent_executions = 1`: una sola instancia a la vez, así el token y los avisos del día en `/tmp` se comparten. Si el contenedor se recicla, puede repetirse un aviso ese día.
- Para cambiar el umbral: `umbral_tna` en `terraform.tfvars` y `terraform apply`.
- Para borrar todo: `terraform destroy` (los parámetros de SSM se borran a mano).
