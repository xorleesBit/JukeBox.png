# Используем официальный образ Python
FROM python:3.13-slim

# Устанавливаем системные зависимости (ffmpeg, opus, build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы проекта
COPY . .

# Команда для запуска бота
CMD ["python", "start.py"]