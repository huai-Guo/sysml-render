package VehicleModel {

    package Interfaces {
        port def PowerPort;
        port def ControlPort;
    }

    package Requirements {
        requirement def PowerContinuityRequirement;
        requirement def MotorControlRequirement;
    }

    package Definitions {
        private import VehicleModel::Interfaces::*;

        part def Battery {
            port powerOut : PowerPort;
        }

        part def Controller {
            port powerIn : PowerPort;
            port motorCommand : ControlPort;
        }

        part def Motor {
            port powerIn : PowerPort;
            port commandIn : ControlPort;
        }

        part def ElectricalSystem {
            part battery : Battery;
            part controller : Controller;
            part motor : Motor;

            connection batteryPower connect
                battery.powerOut to controller.powerIn;

            connection motorControl connect
                controller.motorCommand to motor.commandIn;
        }

        part def Vehicle {
            part electrical : ElectricalSystem;
        }
    }

    package Usages {
        private import VehicleModel::Definitions::*;
        private import VehicleModel::Requirements::*;

        part vehicle : Vehicle;

        requirement powerContinuity : PowerContinuityRequirement;
        requirement motorControl : MotorControlRequirement;
    }
}
