output "lambda_name" {
  value = aws_lambda_function.this.function_name
}

output "log_group" {
  value = aws_cloudwatch_log_group.lambda.name
}

output "schedule" {
  value = "${aws_scheduler_schedule.this.schedule_expression} (${aws_scheduler_schedule.this.schedule_expression_timezone})"
}
