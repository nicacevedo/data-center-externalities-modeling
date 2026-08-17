import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import sys
import time
import random
import math
import json
import requests
import urllib3
import urllib.parse


# Arrival of energy demand
T_day = 24
T = T_day * 7 # time steps
t_range = np.arange(1, T+1, 1)

# Capacity of the data center IT energy cap when processing jobs (independent of the supply of energy,  just from hardware and software)
K_it = 10000 # capacity of the data center IT energy cap when processing jobs (in Watts)

# (1) Job arrivals: Non-Homogeneous Poisson Process (NHPP) or Weibull Inter-arrivals
# To realistically model arrivals, we create # of jobs using a time-varying 
# rate lambda(t).
#   We can model the arrival rate lambda(t) as a sinusoidal baseline combined with noise:
#   lambda(t) = lambda_base + A sin(2pi t/T) + epsilon
lambda_base = 10 # base arrival rate
A = 1 # amplitude of the sinusoidal noise
# epsilon_t is a random noise term with mean 0 and standard deviation sigma
epsilon_t = np.random.normal(loc=0, scale=1, size=T)
lambda_t = lambda_base + A * np.sin(2 * np.pi * t_range / T_day) + epsilon_t
D_t = np.random.poisson(lam=lambda_t, size=T)

plt.plot(t_range, lambda_t)
plt.xlabel('Time')
plt.ylabel('Arrival Rate')
plt.title('Arrival Rate over Time')
plt.savefig('arrival_rate_over_time.png')
# plt.close()
plt.show()


# (2) Job processing time: Lognormal distribution
 
# The processing time of a job is the time it takes to complete the job.
# We can model the processing time as a lognormal distribution.
# The lognormal distribution is a right-skewed distribution that is often used to model the processing time of a job.
# The lognormal distribution is defined by the mean and standard deviation of the log of the processing time.
# The mean and standard deviation of the log of the processing time are 0 and 1 respectively.
# The processing time is the time it takes to complete the job.
mu = 0.1 # mean of the log of the processing time
sigma = 1 # standard deviation of the log of the processing time
S_t = np.random.lognormal(mean=mu, sigma=sigma, size=T)

plt.plot(t_range, S_t, color='red')
plt.xlabel('Time')
plt.ylabel('Processing Time')
plt.title('Processing Time over Time')
plt.savefig('processing_time_over_time.png')
# plt.close()
plt.show()

# (3) Transform the job arrivals and processing time to the energy demand
# The energy demand is the sum of the processing time of all jobs at each time step.

# Transforming to Energy Demand: The Power Model
# To convert job duration and arrivals into energy demand, you cannot simply assign a static "energy per step." A server consumes a massive amount of baseline power just being turned on (idle power), and dynamic power scales non-linearly with utilization.
# Recommendation: The Linear Power Model (Google/Fan Model)
# The industry standard for estimating server power $P$ as a function of CPU utilization $u$ (where $u \in [0, 1]$) is the empirical linear model.
# Server Power Equation:
# $$P(u) = P_{\text{idle}} + (P_{\text{max}} - P_{\text{idle}}) \times u$$
# Where:
# $P_{\text{idle}}$ is the baseline power consumption when the server is idle.
# $P_{\text{max}}$ is the maximum power consumption when the server is running at full utilization.
# $u$ is the CPU utilization.
# The energy demand is the sum of the power consumption of all jobs at each time step.
P_idle = 100 # baseline power consumption when the server is idle
P_max = 1000 # maximum power consumption when the server is running at full utilization
u_t = S_t / K_it # CPU utilization at time t
P_t = P_idle + (P_max - P_idle) * u_t
E_t = D_t * S_t * P_t
# plot the energy demand over time
plt.plot(t_range, E_t)
plt.xlabel('Time')
plt.ylabel('Energy Demand')
plt.title('Energy Demand over Time')
plt.savefig('energy_demand_over_time.png')
plt.close()
plt.show()