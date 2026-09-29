{{- define "radar.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "radar.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "radar.labels" -}}
app.kubernetes.io/name: {{ include "radar.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "radar.redisUrl" -}}
{{- if .Values.redis.enabled -}}
redis://{{ include "radar.fullname" . }}-redis:6379/0
{{- else -}}
{{ .Values.redis.externalUrl }}
{{- end -}}
{{- end -}}

{{/* Environment shared by every role */}}
{{- define "radar.env" -}}
- name: RADAR_REDIS_URL
  value: {{ include "radar.redisUrl" . | quote }}
- name: RADAR_DATABASE_URL
{{- if .Values.database.existingSecret }}
  valueFrom:
    secretKeyRef:
      name: {{ .Values.database.existingSecret }}
      key: RADAR_DATABASE_URL
{{- else }}
  valueFrom:
    secretKeyRef:
      name: {{ include "radar.fullname" . }}-db
      key: RADAR_DATABASE_URL
{{- end }}
- name: RADAR_ADMIN_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.admin.existingSecret | default (printf "%s-admin" (include "radar.fullname" .)) }}
      key: RADAR_ADMIN_TOKEN
      optional: true
- name: RADAR_COUNTRIES
  value: {{ .Values.config.countries | quote }}
- name: RADAR_EXTRACTOR
  value: {{ .Values.config.extractor | quote }}
- name: RADAR_HOST_RATE_LIMITS
  value: {{ .Values.config.hostRateLimits | quote }}
- name: RADAR_CADENCE_HIGH_MINUTES
  value: {{ .Values.config.cadenceHighMinutes | quote }}
- name: RADAR_CADENCE_NORMAL_MINUTES
  value: {{ .Values.config.cadenceNormalMinutes | quote }}
- name: RADAR_CADENCE_LOW_MINUTES
  value: {{ .Values.config.cadenceLowMinutes | quote }}
- name: RADAR_CORS_ORIGINS
  value: {{ .Values.config.corsOrigins | quote }}
- name: RADAR_LOG_JSON
  value: "1"
- name: RADAR_SITE_NAME
  value: {{ .Values.config.siteName | quote }}
- name: RADAR_SITE_ALIASES
  value: {{ .Values.config.siteAliases | quote }}
- name: RADAR_SITE_URL
  value: {{ .Values.config.siteUrl | quote }}
{{- range $k, $v := .Values.config.extraEnv }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end -}}
