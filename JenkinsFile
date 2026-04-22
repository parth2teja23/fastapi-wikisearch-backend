pipeline {
    agent any

    environment {
        REPO_DIR = '/home/fastapi-wikisearch-backend'
        VENV     = "${REPO_DIR}/venv"
    }

    stages {

        stage('Pull') {
            steps {
                echo 'Pulling latest code...'
                dir("${REPO_DIR}") {
                    sh 'git pull origin main'
                }
            }
        }

        stage('Install dependencies') {
            steps {
                echo 'Installing Python dependencies...'
                dir("${REPO_DIR}") {
                    sh "${VENV}/bin/pip install -r requirements.txt"
                }
            }
        }

        stage('Restart service') {
            steps {
                echo 'Restarting FastAPI service...'
                sh 'sudo /bin/systemctl restart wikisearch-api'
            }
        }

        stage('Health check') {
            steps {
                echo 'Checking service is up...'
                sh 'sleep 3'
                sh 'curl -f http://127.0.0.1:8000/api/search?q=india || exit 1'
            }
        }
    }

    post {
        success {
            echo 'Deployment successful!'
        }
        failure {
            echo 'Deployment failed! Check logs above.'
        }
    }
}