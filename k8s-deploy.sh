# k8s-deploy.sh
#!/bin/bash
set -e

NAMESPACE="locationapp"
REGISTRY="your-registry.com"  # Change this to your container registry

echo "☸️ Deploying to Kubernetes..."

# Create namespace
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Deploy infrastructure components first
echo "📦 Deploying infrastructure..."

# Kafka (using Strimzi operator)
kubectl apply -f https://strimzi.io/install/latest?namespace=$NAMESPACE -n $NAMESPACE

# Wait for Strimzi operator
kubectl wait --for=condition=ready pod -l name=strimzi-cluster-operator -n $NAMESPACE --timeout=300s

# Create Kafka cluster
cat <<EOF | kubectl apply -f -
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: locationapp-kafka
  namespace: $NAMESPACE
spec:
  kafka:
    version: 3.6.0
    replicas: 3
    listeners:
      - name: plain
        port: 9092
        type: internal
        tls: false
    config:
      offsets.topic.replication.factor: 3
      transaction.state.log.replication.factor: 3
      transaction.state.log.min.isr: 2
    storage:
      type: jbod
      volumes:
      - id: 0
        type: persistent-claim
        size: 10Gi
        deleteClaim: false
  zookeeper:
    replicas: 3
    storage:
      type: persistent-claim
      size: 5Gi
      deleteClaim: false
  entityOperator:
    topicOperator: {}
    userOperator: {}
EOF

# Redis deployment
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: $NAMESPACE
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
        volumeMounts:
        - name: redis-storage
          mountPath: /data
      volumes:
      - name: redis-storage
        persistentVolumeClaim:
          claimName: redis-pvc
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: redis-pvc
  namespace: $NAMESPACE
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: $NAMESPACE
spec:
  selector:
    app: redis
  ports:
  - port: 6379
    targetPort: 6379
EOF

echo "✅ Kubernetes deployment initiated!"
echo "📊 Monitor with: kubectl get pods -n $NAMESPACE -w"