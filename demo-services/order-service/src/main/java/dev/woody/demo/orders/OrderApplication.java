package dev.woody.demo.orders;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

import dev.woody.demo.orders.configuration.properties.DemoProperties;

@SpringBootApplication
@EnableConfigurationProperties(DemoProperties.class)
public class OrderApplication {

    public static void main(String [] args) {
        SpringApplication.run(OrderApplication.class, args);
    }
}