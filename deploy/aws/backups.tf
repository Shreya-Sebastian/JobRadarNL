# Off-server copies of the nightly database dump. The server can only upload into this bucket; objects are
# removed after 30 days. Costs cents a month (a few MB per night).

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "backups" {
  bucket = "techjobsradar-backups-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "expire-after-30-days"
    status = "Enabled"
    filter {}
    expiration {
      days = 30
    }
  }
}

# The server's own identity: upload-only access to the backup bucket, nothing else
resource "aws_iam_role" "server" {
  name = "radar-server"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "server_backups" {
  name = "upload-backups"
  role = aws_iam_role.server.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = "${aws_s3_bucket.backups.arn}/*"
    }]
  })
}

resource "aws_iam_instance_profile" "server" {
  name = "radar-server"
  role = aws_iam_role.server.name
}

output "backup_bucket" { value = aws_s3_bucket.backups.bucket }
