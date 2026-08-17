There is no single universal number for $\lambda_{\text{base}}$, because the baseline arrival rate depends entirely on two factors: the **scale of your simulated data center** (are you simulating a rack of 10 servers or a massive Google-style cell of 12,000?) and the **type of workload**.

However, based on public traces from major cloud providers and academic research, here are the typical hourly arrival rates you should use to make your simulation realistic.

### 1. Empirical Values by Workload Type

If you want to match real-world data center sizes, here are the average $\lambda_{\text{base}}$ values derived from industry traces:

| Workload Type | Real-World Example | $\lambda_{\text{base}}$ (Arrivals per Hour) | Job Characteristics |
| --- | --- | --- | --- |
| **Traditional HPC / Supercomputing** | Grid5000, Argonne Traces | **15 to 50** per cluster | Massive jobs taking hours/days. Usually queued. |
| **Cloud VM Provisioning** | Azure VM Traces (2017) | **500 to 2,000** per zone | VMs spun up for hours/weeks. Moderate arrival volume. |
| **Hyperscale Container/Task** | Google Borg Trace (12k servers) | **35,000 to 45,000** per cluster | Highly mixed. Translates to ~3 tasks per server, per hour. |
| **Serverless / Microservices** | Azure Functions Trace (2019) | **100,000 to 5,000,000+** | Extreme burstiness. Jobs run for milliseconds to seconds. |

### 2. The "Utilization-Targeting" Formula (Best Practice)

In computer science simulation research, you rarely pick a hardcoded $\lambda_{\text{base}}$. Instead, you **reverse-engineer it** to ensure your simulated data center operates at a realistic load.

Modern data centers usually target an average CPU utilization of **40% to 70%** (leaving headroom for burstiness). To find your ideal hourly $\lambda_{\text{base}}$, use a variation of Little's Law:

$$\lambda_{\text{base}} = \frac{\rho \times C}{E[S]}$$

Where:

* **$\rho$ (Target Utilization):** e.g., $0.60$ for a 60% average load.
* **$C$ (Total Capacity):** The total number of servers (or total CPU cores) in your simulation.
* **$E[S]$ (Average Job Duration):** The mean time a job takes, **converted to hours**. (If you use the Lognormal distribution from the previous step, calculate the expected value/mean of that distribution in hours).

**Example Calculation:**
Imagine you are simulating a cluster of **500 servers** ($C = 500$), and your jobs average **15 minutes** ($E[S] = 0.25$ hours). You want the data center to run at **60% utilization** ($\rho = 0.60$).

$$\lambda_{\text{base}} = \frac{0.60 \times 500}{0.25} = 1,200 \text{ jobs per hour}$$

### 3. Setting the Amplitude ($A$) for the Diurnal Pattern

If you use the sinusoidal formula $\lambda(t) = \lambda_{\text{base}} + A \sin\left(\frac{2\pi t}{24}\right) + \epsilon$:

* Set $A$ (the peak variation amplitude) to be roughly **$30\%$ to $50\%$ of $\lambda_{\text{base}}$**.
* For example, if $\lambda_{\text{base}} = 1,200$, setting $A = 400$ means your traffic will realistically peak at 1,600 arrivals/hour during the daytime and drop to 800 arrivals/hour in the middle of the night.